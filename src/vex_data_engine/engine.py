import os
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from vex_contracts.data_engine import (
    CacheArtifact,
    CrossTimeframeReport,
    DataEngineConfig,
    DataFileReport,
    DataImportReport,
    DataQualityIssue,
)
from vex_contracts.dataset import DatasetFile, DatasetManifest
from vex_contracts.enums import CacheMode, DataIssueSeverity
from vex_contracts.identifiers import new_identifier
from vex_contracts.serialization import dump_json, dump_yaml, fingerprint
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.audit import audit_cross_timeframe_group_files
from vex_data_engine.cache import (
    StreamingCacheWriter,
    artifact_paths,
    build_cache_key,
    read_cached_artifact,
    require_cached_artifact,
)
from vex_data_engine.discovery import discover_mt5_files, parse_mt5_filename
from vex_data_engine.exceptions import DataDiscoveryError, DataValidationError
from vex_data_engine.hashing import sha256_file
from vex_data_engine.inspection import read_last_open_time
from vex_data_engine.models import ImportOutcome, StreamSummary
from vex_data_engine.reader import Mt5CsvStream


def _ns_to_datetime(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)


def _issue(
    severity: DataIssueSeverity,
    code: str,
    message: str,
    **details: str | int | float | bool | None,
) -> DataQualityIssue:
    return DataQualityIssue(
        severity=severity,
        code=code,
        message=message,
        details=details,
    )


def _issue_counts(issues: Iterable[DataQualityIssue]) -> tuple[int, int, int]:
    values = tuple(issues)
    warnings = sum(issue.severity is DataIssueSeverity.WARNING for issue in values)
    errors = sum(issue.severity is DataIssueSeverity.ERROR for issue in values)
    return len(values), warnings, errors


@dataclass(frozen=True, slots=True)
class _ImportedFile:
    key: tuple[str, Timeframe]
    source_sha256: str
    report: DataFileReport
    resolved_manifest_file: DatasetFile


class Mt5DataEngine:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()

    def import_dataset(
        self,
        manifest: DatasetManifest,
        symbol_profiles: dict[str, SymbolProfile],
        config: DataEngineConfig,
    ) -> ImportOutcome:
        resolved_files = self._resolve_files(manifest)
        self._validate_profiles(manifest, symbol_profiles)
        completion_watermark = self._resolve_completion_watermark(
            manifest,
            resolved_files,
            config,
        )
        source_hashes: dict[tuple[str, Timeframe], str] = {}
        file_reports: dict[tuple[str, Timeframe], DataFileReport] = {}
        resolved_manifest_files: dict[tuple[str, Timeframe], DatasetFile] = {}

        workers = self._resolve_import_workers(len(manifest.files), config)
        if workers <= 1:
            imported_files = tuple(
                self._import_file(
                    manifest,
                    manifest_file,
                    resolved_files[(manifest_file.symbol, manifest_file.timeframe)],
                    symbol_profiles[manifest_file.symbol],
                    completion_watermark,
                    config,
                )
                for manifest_file in manifest.files
            )
        else:
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="vex-data-import",
            ) as executor:
                futures = tuple(
                    executor.submit(
                        self._import_file,
                        manifest,
                        manifest_file,
                        resolved_files[(manifest_file.symbol, manifest_file.timeframe)],
                        symbol_profiles[manifest_file.symbol],
                        completion_watermark,
                        config,
                    )
                    for manifest_file in manifest.files
                )
                imported_files = tuple(future.result() for future in futures)

        for imported in imported_files:
            source_hashes[imported.key] = imported.source_sha256
            file_reports[imported.key] = imported.report
            resolved_manifest_files[imported.key] = imported.resolved_manifest_file

        cross_reports = self._run_cross_timeframe_audits(manifest, file_reports, config)
        ordered_reports = tuple(
            file_reports[(item.symbol, item.timeframe)] for item in manifest.files
        )
        warning_count = sum(report.warning_count for report in ordered_reports)
        error_count = sum(report.error_count for report in ordered_reports)
        success = error_count == 0 and (not config.fail_on_warnings or warning_count == 0)
        dataset_content_hash = fingerprint(
            [
                {
                    "symbol": item.symbol,
                    "timeframe": item.timeframe,
                    "sha256": source_hashes[(item.symbol, item.timeframe)],
                }
                for item in manifest.files
            ]
        )
        resolved_manifest = manifest.model_copy(
            update={
                "files": tuple(
                    resolved_manifest_files[(item.symbol, item.timeframe)]
                    for item in manifest.files
                ),
                "content_hash": dataset_content_hash,
            }
        )
        report = DataImportReport(
            report_id=new_identifier("data_report"),
            dataset_id=manifest.dataset_id,
            dataset_version=manifest.version,
            dataset_fingerprint=fingerprint(resolved_manifest),
            config_fingerprint=fingerprint(config),
            completion_watermark=completion_watermark,
            success=success,
            source_row_count=sum(item.source_row_count for item in ordered_reports),
            output_row_count=sum(item.output_row_count for item in ordered_reports),
            complete_row_count=sum(item.complete_row_count for item in ordered_reports),
            incomplete_row_count=sum(item.incomplete_row_count for item in ordered_reports),
            warning_count=warning_count,
            error_count=error_count,
            files=ordered_reports,
            cross_timeframe_reports=cross_reports,
        )
        output_root = self.project_root / config.cache_root / manifest.dataset_id / manifest.version
        report_path = output_root / "import-report.json"
        resolved_manifest_path = output_root / "dataset.resolved.yaml"
        dump_json(report, report_path)
        dump_yaml(resolved_manifest, resolved_manifest_path)
        if not success:
            raise DataValidationError(
                f"dataset import failed with {error_count} errors and {warning_count} warnings; "
                f"report: {report_path}"
            )
        return ImportOutcome(
            report=report,
            report_path=report_path,
            resolved_manifest_path=resolved_manifest_path,
        )

    @staticmethod
    def _resolve_import_workers(file_count: int, config: DataEngineConfig) -> int:
        if file_count <= 1:
            return file_count
        if config.file_import_workers > 0:
            return min(file_count, config.file_import_workers)
        cpu_count = os.cpu_count() or 1
        automatic = max(1, min(4, cpu_count // 2 or 1))
        if not config.csv_use_threads:
            automatic = min(automatic, 2)
        return min(file_count, automatic)

    def _import_file(
        self,
        manifest: DatasetManifest,
        manifest_file: DatasetFile,
        source_path: Path,
        profile: SymbolProfile,
        completion_watermark: datetime,
        config: DataEngineConfig,
    ) -> _ImportedFile:
        key = (manifest_file.symbol, manifest_file.timeframe)
        source_sha256 = sha256_file(source_path)
        cache_key = build_cache_key(
            source_sha256,
            profile,
            config,
            completion_watermark.isoformat(),
        )
        parquet_path, metadata_path = artifact_paths(
            self.project_root,
            config,
            manifest.dataset_id,
            manifest.version,
            manifest_file.symbol,
            manifest_file.timeframe,
        )
        cached_artifact = self._resolve_existing_artifact(
            config,
            parquet_path,
            metadata_path,
            cache_key,
        )
        writer = self._create_writer(
            cached_artifact,
            manifest_file,
            source_sha256,
            cache_key,
            parquet_path,
            metadata_path,
            config,
        )
        stream = Mt5CsvStream(
            source_path,
            manifest_file.symbol,
            manifest_file.timeframe,
            manifest.source_timezone,
            profile,
            completion_watermark,
            config,
        )
        try:
            for batch in stream:
                if writer is not None:
                    writer.write(batch)
                del batch
            summary = stream.summary()
            issues = [*summary.issues]
            issues.extend(
                self._validate_manifest_metadata(
                    manifest_file,
                    source_path,
                    source_sha256,
                    summary,
                )
            )
            _, _, error_count = _issue_counts(issues)
            artifact = self._finalize_artifact(
                writer,
                cached_artifact,
                summary,
                error_count,
            )
        except Exception:
            if writer is not None:
                writer.abort()
            raise

        actual_start, actual_end = self._actual_range(summary)
        issue_count, warning_count, error_count = _issue_counts(issues)
        report = DataFileReport(
            symbol=manifest_file.symbol,
            timeframe=manifest_file.timeframe,
            source_path=source_path.relative_to(self.project_root).as_posix(),
            delimiter="\t" if summary.delimiter == "\t" else summary.delimiter,
            source_row_count=summary.source_row_count,
            output_row_count=summary.output_row_count,
            complete_row_count=summary.complete_row_count,
            incomplete_row_count=summary.incomplete_row_count,
            actual_start=actual_start,
            actual_end=actual_end,
            duplicate_timestamp_count=summary.duplicate_timestamp_count,
            out_of_order_count=summary.out_of_order_count,
            gap_count=summary.gap_count,
            estimated_missing_bars=summary.estimated_missing_bars,
            maximum_gap_seconds=summary.maximum_gap_seconds,
            issue_count=issue_count,
            warning_count=warning_count,
            error_count=error_count,
            issues=tuple(issues),
            artifact=artifact,
        )
        resolved_manifest_file = manifest_file.model_copy(
            update={
                "relative_path": source_path.relative_to(
                    self.project_root / manifest.root_path
                ).as_posix(),
                "actual_start": actual_start,
                "actual_end": actual_end,
                "row_count": summary.source_row_count,
                "size_bytes": source_path.stat().st_size,
                "sha256": source_sha256,
            }
        )
        return _ImportedFile(
            key=key,
            source_sha256=source_sha256,
            report=report,
            resolved_manifest_file=resolved_manifest_file,
        )

    def _resolve_existing_artifact(
        self,
        config: DataEngineConfig,
        parquet_path: Path,
        metadata_path: Path,
        cache_key: str,
    ) -> CacheArtifact | None:
        if config.cache_mode is CacheMode.READ_ONLY:
            return require_cached_artifact(
                self.project_root,
                parquet_path,
                metadata_path,
                cache_key,
            )
        if config.cache_mode is CacheMode.REUSE:
            return read_cached_artifact(
                self.project_root,
                parquet_path,
                metadata_path,
                cache_key,
            )
        return None

    def _create_writer(
        self,
        cached_artifact: CacheArtifact | None,
        manifest_file: DatasetFile,
        source_sha256: str,
        cache_key: str,
        parquet_path: Path,
        metadata_path: Path,
        config: DataEngineConfig,
    ) -> StreamingCacheWriter | None:
        if cached_artifact is not None:
            return None
        if config.cache_mode is CacheMode.READ_ONLY:
            return None
        return StreamingCacheWriter(
            self.project_root,
            parquet_path,
            metadata_path,
            manifest_file.symbol,
            manifest_file.timeframe,
            source_sha256,
            cache_key,
            config,
        )

    def _finalize_artifact(
        self,
        writer: StreamingCacheWriter | None,
        cached_artifact: CacheArtifact | None,
        summary: StreamSummary,
        error_count: int,
    ) -> CacheArtifact | None:
        if error_count:
            if writer is not None:
                writer.abort()
            return None
        if writer is None:
            return cached_artifact
        return writer.finalize(
            summary.output_row_count,
            summary.complete_row_count,
            summary.incomplete_row_count,
        )

    def _run_cross_timeframe_audits(
        self,
        manifest: DatasetManifest,
        file_reports: dict[tuple[str, Timeframe], DataFileReport],
        config: DataEngineConfig,
    ) -> tuple[CrossTimeframeReport, ...]:
        audit_bases = self._resolve_audit_bases(manifest, config)
        if not audit_bases:
            return ()
        results: list[CrossTimeframeReport] = []
        for symbol, base_timeframe in audit_bases.items():
            base_report = file_reports[(symbol, base_timeframe)]
            if base_report.error_count or base_report.artifact is None:
                continue
            target_paths = {
                item.timeframe: self.project_root / report.artifact.relative_path
                for item in manifest.files
                if item.symbol == symbol and item.timeframe is not base_timeframe
                for report in [file_reports[(symbol, item.timeframe)]]
                if not report.error_count and report.artifact is not None
            }
            symbol_results = audit_cross_timeframe_group_files(
                symbol,
                base_timeframe,
                self.project_root / base_report.artifact.relative_path,
                target_paths,
                config,
            )
            results.extend(symbol_results)
            for audit in symbol_results:
                discrepancy_count = (
                    audit.mismatching_bar_count
                    + audit.source_only_bar_count
                    + audit.aggregate_only_bar_count
                )
                if not discrepancy_count:
                    continue
                target_key = (symbol, audit.target_timeframe)
                target_report = file_reports[target_key]
                issue = _issue(
                    DataIssueSeverity.WARNING,
                    "CROSS_TIMEFRAME_MISMATCH",
                    "source bars differ from base-timeframe aggregation",
                    base_timeframe=audit.base_timeframe.value,
                    target_timeframe=audit.target_timeframe.value,
                    mismatching_bar_count=audit.mismatching_bar_count,
                    source_only_bar_count=audit.source_only_bar_count,
                    aggregate_only_bar_count=audit.aggregate_only_bar_count,
                )
                file_reports[target_key] = self._append_issue(target_report, issue)
        return tuple(results)

    def _append_issue(
        self,
        report: DataFileReport,
        issue: DataQualityIssue,
    ) -> DataFileReport:
        issues = (*report.issues, issue)
        issue_count, warning_count, error_count = _issue_counts(issues)
        return report.model_copy(
            update={
                "issues": issues,
                "issue_count": issue_count,
                "warning_count": warning_count,
                "error_count": error_count,
            }
        )

    def _resolve_files(self, manifest: DatasetManifest) -> dict[tuple[str, Timeframe], Path]:
        root = (self.project_root / manifest.root_path).resolve()
        if not root.is_relative_to(self.project_root):
            raise DataDiscoveryError("dataset root escapes the project root")
        discovered = None
        resolved: dict[tuple[str, Timeframe], Path] = {}
        for item in manifest.files:
            direct = root / item.relative_path
            if direct.exists():
                parsed = parse_mt5_filename(direct)
                if parsed.symbol != item.symbol or parsed.timeframe is not item.timeframe:
                    raise DataDiscoveryError(f"manifest identity mismatch: {direct.name}")
                resolved[(item.symbol, item.timeframe)] = direct
                continue
            if discovered is None:
                discovered = {
                    (entry.symbol, entry.timeframe): entry.path
                    for entry in discover_mt5_files(root)
                }
            fallback = discovered.get((item.symbol, item.timeframe))
            if fallback is None:
                raise DataDiscoveryError(
                    f"missing MT5 file for {item.symbol}:{item.timeframe.value}"
                )
            resolved[(item.symbol, item.timeframe)] = fallback
        return resolved

    def _validate_profiles(
        self,
        manifest: DatasetManifest,
        profiles: dict[str, SymbolProfile],
    ) -> None:
        missing = sorted({item.symbol for item in manifest.files}.difference(profiles))
        if missing:
            raise DataValidationError(f"missing symbol profiles: {', '.join(missing)}")
        mismatches = [symbol for symbol, profile in profiles.items() if profile.symbol != symbol]
        if mismatches:
            raise DataValidationError(f"symbol profile key mismatch: {', '.join(mismatches)}")

    def _resolve_completion_watermark(
        self,
        manifest: DatasetManifest,
        resolved_files: dict[tuple[str, Timeframe], Path],
        config: DataEngineConfig,
    ) -> datetime:
        if config.as_of_time is not None:
            return config.as_of_time.astimezone(UTC)
        fixed = [item for item in manifest.files if item.timeframe.seconds is not None]
        if not fixed:
            raise DataValidationError(
                "a fixed-duration timeframe is required for watermark inference"
            )
        minimum_seconds = min(item.timeframe.seconds or 0 for item in fixed)
        finest = [item for item in fixed if item.timeframe.seconds == minimum_seconds]
        per_symbol: dict[str, datetime] = {}
        for item in finest:
            last_open = read_last_open_time(
                resolved_files[(item.symbol, item.timeframe)],
                item.timeframe,
                manifest.source_timezone,
            )
            current = per_symbol.get(item.symbol)
            per_symbol[item.symbol] = last_open if current is None else max(current, last_open)
        return min(per_symbol.values())

    def _validate_manifest_metadata(
        self,
        manifest_file: DatasetFile,
        source_path: Path,
        source_sha256: str,
        summary: StreamSummary,
    ) -> tuple[DataQualityIssue, ...]:
        issues: list[DataQualityIssue] = []
        if manifest_file.sha256 is not None and manifest_file.sha256 != source_sha256:
            issues.append(
                _issue(
                    DataIssueSeverity.ERROR,
                    "SOURCE_HASH_MISMATCH",
                    "source file hash differs from the manifest",
                    expected=manifest_file.sha256,
                    actual=source_sha256,
                )
            )
        size_bytes = source_path.stat().st_size
        if manifest_file.size_bytes is not None and manifest_file.size_bytes != size_bytes:
            issues.append(
                _issue(
                    DataIssueSeverity.ERROR,
                    "SOURCE_SIZE_MISMATCH",
                    "source file size differs from the manifest",
                    expected=manifest_file.size_bytes,
                    actual=size_bytes,
                )
            )
        if (
            manifest_file.row_count is not None
            and manifest_file.row_count != summary.source_row_count
        ):
            issues.append(
                _issue(
                    DataIssueSeverity.ERROR,
                    "SOURCE_ROW_COUNT_MISMATCH",
                    "source row count differs from the manifest",
                    expected=manifest_file.row_count,
                    actual=summary.source_row_count,
                )
            )
        actual_start, actual_end = self._actual_range(summary)
        if (
            manifest_file.declared_start is not None
            and actual_start is not None
            and manifest_file.declared_start != actual_start
        ):
            issues.append(
                _issue(
                    DataIssueSeverity.ERROR,
                    "DECLARED_START_MISMATCH",
                    "first bar time differs from the manifest",
                    expected=manifest_file.declared_start.isoformat(),
                    actual=actual_start.isoformat(),
                )
            )
        if (
            manifest_file.declared_end is not None
            and actual_end is not None
            and manifest_file.declared_end != actual_end
        ):
            issues.append(
                _issue(
                    DataIssueSeverity.ERROR,
                    "DECLARED_END_MISMATCH",
                    "last bar time differs from the manifest",
                    expected=manifest_file.declared_end.isoformat(),
                    actual=actual_end.isoformat(),
                )
            )
        return tuple(issues)

    def _actual_range(
        self,
        summary: StreamSummary,
    ) -> tuple[datetime | None, datetime | None]:
        if summary.actual_start_ns is None or summary.actual_end_ns is None:
            return None, None
        return _ns_to_datetime(summary.actual_start_ns), _ns_to_datetime(summary.actual_end_ns)

    def _resolve_audit_bases(
        self,
        manifest: DatasetManifest,
        config: DataEngineConfig,
    ) -> dict[str, Timeframe]:
        if not config.cross_timeframe_audit:
            return {}
        result: dict[str, Timeframe] = {}
        for symbol in sorted({item.symbol for item in manifest.files}):
            available = [
                item.timeframe
                for item in manifest.files
                if item.symbol == symbol and item.timeframe.seconds is not None
            ]
            if not available:
                raise DataValidationError(
                    f"a fixed-duration timeframe is required for audit: {symbol}"
                )
            base = config.audit_base_timeframe or min(
                available,
                key=lambda item: item.seconds or 10**18,
            )
            if base not in available:
                raise DataValidationError(
                    f"audit base timeframe {base.value} is unavailable for {symbol}"
                )
            result[symbol] = base
        return result
