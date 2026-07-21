import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol, cast

import pyarrow as pa
import pyarrow.parquet as pq

from vex_contracts.data_engine import CacheArtifact, DataEngineConfig
from vex_contracts.serialization import fingerprint
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.exceptions import CacheMissError
from vex_data_engine.hashing import sha256_file

_CACHE_SCHEMA_VERSION = "1"


class _ArrowTable(Protocol):
    @property
    def num_rows(self) -> int: ...

    @property
    def schema(self) -> object: ...


def build_cache_key(
    source_sha256: str,
    profile: SymbolProfile,
    config: DataEngineConfig,
    completion_watermark: str,
) -> str:
    return fingerprint(
        {
            "cache_schema_version": _CACHE_SCHEMA_VERSION,
            "source_sha256": source_sha256,
            "profile": profile,
            "trailing_bar_policy": config.trailing_bar_policy,
            "as_of_time": config.as_of_time,
            "parquet_compression": config.parquet_compression,
            "parquet_compression_level": config.parquet_compression_level,
            "row_group_size": config.row_group_size,
            "csv_block_size_bytes": config.csv_block_size_bytes,
            "csv_batch_rows": config.csv_batch_rows,
            "csv_use_threads": config.csv_use_threads,
            "completion_watermark": completion_watermark,
        }
    )


def artifact_paths(
    project_root: Path,
    config: DataEngineConfig,
    dataset_id: str,
    dataset_version: str,
    symbol: str,
    timeframe: Timeframe,
) -> tuple[Path, Path]:
    directory = project_root / config.cache_root / dataset_id / dataset_version / symbol
    parquet_path = directory / f"{timeframe.value}.parquet"
    metadata_path = directory / f"{timeframe.value}.meta.json"
    return parquet_path, metadata_path


def read_cached_artifact(
    project_root: Path,
    parquet_path: Path,
    metadata_path: Path,
    expected_cache_key: str,
) -> CacheArtifact | None:
    if not parquet_path.exists() or not metadata_path.exists():
        return None
    with metadata_path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    artifact = CacheArtifact.model_validate(data)
    if artifact.cache_key != expected_cache_key:
        return None
    if sha256_file(parquet_path) != artifact.content_sha256:
        return None
    relative_path = parquet_path.relative_to(project_root).as_posix()
    return artifact.model_copy(update={"relative_path": relative_path, "reused": True})


def require_cached_artifact(
    project_root: Path,
    parquet_path: Path,
    metadata_path: Path,
    expected_cache_key: str,
) -> CacheArtifact:
    artifact = read_cached_artifact(
        project_root,
        parquet_path,
        metadata_path,
        expected_cache_key,
    )
    if artifact is None:
        raise CacheMissError(f"cache artifact is missing or stale: {parquet_path}")
    return artifact


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json.tmp",
        dir=path.parent,
        delete=False,
    ) as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class StreamingCacheWriter:
    def __init__(
        self,
        project_root: Path,
        parquet_path: Path,
        metadata_path: Path,
        symbol: str,
        timeframe: Timeframe,
        source_sha256: str,
        cache_key: str,
        config: DataEngineConfig,
    ) -> None:
        self.project_root = project_root
        self.parquet_path = parquet_path
        self.metadata_path = metadata_path
        self.symbol = symbol
        self.timeframe = timeframe
        self.source_sha256 = source_sha256
        self.cache_key = cache_key
        self.config = config
        self.parquet_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="wb",
            suffix=".parquet.tmp",
            dir=self.parquet_path.parent,
            delete=False,
        ) as stream:
            self.temporary_path = Path(stream.name)
        self._writer: pq.ParquetWriter | None = None
        self._closed = False

    def write(self, batch: object) -> None:
        if self._closed:
            raise RuntimeError("streaming cache writer is closed")
        if isinstance(batch, pa.Table):
            raw_table = batch
        elif isinstance(batch, pa.RecordBatch):
            raw_table = pa.Table.from_batches([batch])
        else:
            raise TypeError(f"unsupported Arrow batch type: {type(batch).__name__}")
        table = cast(_ArrowTable, raw_table)
        if table.num_rows == 0:
            return
        if self._writer is None:
            compression_level = (
                self.config.parquet_compression_level
                if self.config.parquet_compression == "zstd"
                else None
            )
            self._writer = pq.ParquetWriter(
                self.temporary_path,
                table.schema,
                compression=self.config.parquet_compression,
                compression_level=compression_level,
                write_statistics=True,
                use_dictionary=False,
            )
        self._writer.write_table(table, row_group_size=self.config.row_group_size)

    def finalize(
        self,
        row_count: int,
        complete_row_count: int,
        incomplete_row_count: int,
    ) -> CacheArtifact:
        if self._closed:
            raise RuntimeError("streaming cache writer is closed")
        if self._writer is None:
            self.abort()
            raise ValueError("cannot finalize an empty cache artifact")
        self._writer.close()
        self._closed = True
        os.replace(self.temporary_path, self.parquet_path)
        artifact = CacheArtifact(
            symbol=self.symbol,
            timeframe=self.timeframe,
            relative_path=self.parquet_path.relative_to(self.project_root).as_posix(),
            row_count=row_count,
            complete_row_count=complete_row_count,
            incomplete_row_count=incomplete_row_count,
            content_sha256=sha256_file(self.parquet_path),
            source_sha256=self.source_sha256,
            cache_key=self.cache_key,
            size_bytes=self.parquet_path.stat().st_size,
            reused=False,
        )
        _write_json_atomic(self.metadata_path, artifact.model_dump(mode="json"))
        return artifact

    def abort(self) -> None:
        if self._closed:
            return
        if self._writer is not None:
            self._writer.close()
        self.temporary_path.unlink(missing_ok=True)
        self._closed = True
