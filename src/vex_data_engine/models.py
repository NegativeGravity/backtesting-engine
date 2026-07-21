from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

from vex_contracts.data_engine import DataImportReport, DataQualityIssue
from vex_contracts.timeframes import Timeframe


@dataclass(frozen=True, slots=True)
class ParsedMt5Filename:
    path: Path
    symbol: str
    timeframe: Timeframe
    declared_start_local: datetime
    declared_end_local: datetime
    canonical_name: str


@dataclass(frozen=True, slots=True)
class CsvDialect:
    delimiter: str
    columns: tuple[str, ...]
    has_time_column: bool
    encoding: str


@dataclass(frozen=True, slots=True)
class ParsedFrame:
    frame: pl.DataFrame
    source_row_count: int
    delimiter: str
    issues: tuple[DataQualityIssue, ...]
    duplicate_timestamp_count: int
    out_of_order_count: int
    gap_count: int
    estimated_missing_bars: int
    maximum_gap_seconds: int


@dataclass(frozen=True, slots=True)
class BarCloseBatch:
    close_time_ns: int
    bars: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    report: DataImportReport
    report_path: Path
    resolved_manifest_path: Path


@dataclass(frozen=True, slots=True)
class StreamSummary:
    source_row_count: int
    output_row_count: int
    complete_row_count: int
    incomplete_row_count: int
    delimiter: str
    issues: tuple[DataQualityIssue, ...]
    duplicate_timestamp_count: int
    out_of_order_count: int
    gap_count: int
    estimated_missing_bars: int
    maximum_gap_seconds: int
    actual_start_ns: int | None
    actual_end_ns: int | None
