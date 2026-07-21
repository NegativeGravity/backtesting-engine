from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import AwareDatetime, Field, NonNegativeInt, PositiveInt, field_validator

from vex_contracts.base import ContractModel
from vex_contracts.enums import CacheMode, DataIssueSeverity, TrailingBarPolicy
from vex_contracts.identifiers import Identifier, Sha256Hex, SymbolCode
from vex_contracts.timeframes import Timeframe
from vex_contracts.version import CONTRACT_SCHEMA_VERSION, SchemaVersion


class DataEngineConfig(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    cache_root: str = "data/cache"
    cache_mode: CacheMode = CacheMode.REUSE
    trailing_bar_policy: TrailingBarPolicy = TrailingBarPolicy.MARK_INCOMPLETE
    as_of_time: AwareDatetime | None = None
    parquet_compression: Literal["zstd", "snappy", "lz4", "uncompressed"] = "zstd"
    parquet_compression_level: int | None = Field(default=6, ge=1, le=22)
    row_group_size: PositiveInt = 131072
    csv_block_size_bytes: PositiveInt = 1048576
    csv_batch_rows: PositiveInt = 65536
    csv_use_threads: bool = False
    max_issue_samples: PositiveInt = 100
    fail_on_warnings: bool = False
    cross_timeframe_audit: bool = True
    audit_base_timeframe: Timeframe | None = None
    price_tolerance_ticks: NonNegativeInt = 0
    compare_tick_volume: bool = True

    @field_validator("cache_root")
    @classmethod
    def validate_cache_root(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("cache_root must be repository-relative")
        return path.as_posix()


class DataQualityIssue(ContractModel):
    severity: DataIssueSeverity
    code: str = Field(min_length=3, max_length=80, pattern=r"^[A-Z][A-Z0-9_]+$")
    message: str = Field(min_length=1, max_length=1000)
    row_number: PositiveInt | None = None
    open_time_ns: NonNegativeInt | None = None
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class CacheArtifact(ContractModel):
    symbol: SymbolCode
    timeframe: Timeframe
    relative_path: str = Field(min_length=1, max_length=512)
    row_count: NonNegativeInt
    complete_row_count: NonNegativeInt
    incomplete_row_count: NonNegativeInt
    content_sha256: Sha256Hex
    source_sha256: Sha256Hex
    cache_key: Sha256Hex
    size_bytes: NonNegativeInt
    reused: bool = False


class DataFileReport(ContractModel):
    symbol: SymbolCode
    timeframe: Timeframe
    source_path: str = Field(min_length=1, max_length=512)
    delimiter: str = Field(min_length=1, max_length=2)
    source_row_count: NonNegativeInt
    output_row_count: NonNegativeInt
    complete_row_count: NonNegativeInt
    incomplete_row_count: NonNegativeInt
    actual_start: AwareDatetime | None = None
    actual_end: AwareDatetime | None = None
    duplicate_timestamp_count: NonNegativeInt = 0
    out_of_order_count: NonNegativeInt = 0
    gap_count: NonNegativeInt = 0
    estimated_missing_bars: NonNegativeInt = 0
    maximum_gap_seconds: NonNegativeInt = 0
    issue_count: NonNegativeInt = 0
    warning_count: NonNegativeInt = 0
    error_count: NonNegativeInt = 0
    issues: tuple[DataQualityIssue, ...] = ()
    artifact: CacheArtifact | None = None


class CrossTimeframeMismatch(ContractModel):
    open_time_ns: NonNegativeInt
    fields: tuple[str, ...] = Field(min_length=1)
    source_values: dict[str, int]
    aggregated_values: dict[str, int]


class CrossTimeframeReport(ContractModel):
    symbol: SymbolCode
    base_timeframe: Timeframe
    target_timeframe: Timeframe
    compared_bar_count: NonNegativeInt
    matching_bar_count: NonNegativeInt
    mismatching_bar_count: NonNegativeInt
    source_only_bar_count: NonNegativeInt
    aggregate_only_bar_count: NonNegativeInt
    mismatch_samples: tuple[CrossTimeframeMismatch, ...] = ()


class DataImportReport(ContractModel):
    schema_version: SchemaVersion = CONTRACT_SCHEMA_VERSION
    report_id: Identifier
    dataset_id: Identifier
    dataset_version: str = Field(min_length=1, max_length=64)
    dataset_fingerprint: Sha256Hex
    config_fingerprint: Sha256Hex
    generated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    completion_watermark: AwareDatetime
    success: bool
    source_row_count: NonNegativeInt
    output_row_count: NonNegativeInt
    complete_row_count: NonNegativeInt
    incomplete_row_count: NonNegativeInt
    warning_count: NonNegativeInt
    error_count: NonNegativeInt
    files: tuple[DataFileReport, ...]
    cross_timeframe_reports: tuple[CrossTimeframeReport, ...] = ()
