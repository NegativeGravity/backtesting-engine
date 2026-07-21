import heapq
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import polars as pl
import pyarrow.parquet as pq

from vex_contracts.data_engine import DataImportReport
from vex_contracts.serialization import load_json
from vex_contracts.timeframes import Timeframe
from vex_data_engine.exceptions import CacheMissError
from vex_data_engine.models import BarCloseBatch


def _as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    raise TypeError("expected integer value")


class ParquetBarStore:
    def __init__(self, project_root: str | Path, report: DataImportReport) -> None:
        self.project_root = Path(project_root).resolve()
        self.report = report
        self._artifacts = {
            (file_report.symbol, file_report.timeframe): file_report.artifact
            for file_report in report.files
            if file_report.artifact is not None
        }

    @classmethod
    def from_report_path(
        cls,
        project_root: str | Path,
        report_path: str | Path,
    ) -> "ParquetBarStore":
        report = DataImportReport.model_validate(load_json(report_path))
        return cls(project_root, report)

    def available(self) -> tuple[tuple[str, Timeframe], ...]:
        return tuple(sorted(self._artifacts, key=lambda item: (item[0], item[1].value)))

    def scan(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time_ns: int | None = None,
        end_time_ns: int | None = None,
        complete_only: bool = True,
    ) -> pl.LazyFrame:
        artifact = self._artifacts.get((symbol, timeframe))
        if artifact is None:
            raise CacheMissError(f"no cache artifact for {symbol}:{timeframe.value}")
        path = self.project_root / artifact.relative_path
        if not path.exists():
            raise CacheMissError(f"cache artifact does not exist: {path}")
        query = pl.scan_parquet(path)
        if start_time_ns is not None:
            query = query.filter(pl.col("open_time_ns") >= start_time_ns)
        if end_time_ns is not None:
            query = query.filter(pl.col("open_time_ns") < end_time_ns)
        if complete_only:
            query = query.filter(pl.col("is_complete"))
        return query

    def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time_ns: int | None = None,
        end_time_ns: int | None = None,
        complete_only: bool = True,
        limit: int | None = None,
    ) -> pl.DataFrame:
        query = self.scan(
            symbol,
            timeframe,
            start_time_ns,
            end_time_ns,
            complete_only,
        ).sort("open_time_ns")
        if limit is not None:
            query = query.head(limit)
        return query.collect()

    def latest_closed(
        self,
        symbol: str,
        timeframe: Timeframe,
        event_time_ns: int,
    ) -> dict[str, object] | None:
        frame = (
            self.scan(symbol, timeframe, complete_only=True)
            .filter(pl.col("close_time_ns") <= event_time_ns)
            .sort("close_time_ns", descending=True)
            .head(1)
            .collect()
        )
        if frame.is_empty():
            return None
        return frame.row(0, named=True)

    def window(
        self,
        symbol: str,
        timeframe: Timeframe,
        event_time_ns: int,
        count: int,
    ) -> pl.DataFrame:
        return (
            self.scan(symbol, timeframe, complete_only=True)
            .filter(pl.col("close_time_ns") <= event_time_ns)
            .sort("close_time_ns", descending=True)
            .head(count)
            .sort("close_time_ns")
            .collect()
        )

    def iter_close_batches(
        self,
        subscriptions: tuple[tuple[str, Timeframe], ...],
        start_time_ns: int | None = None,
        end_time_ns: int | None = None,
    ) -> Iterator[BarCloseBatch]:
        streams = tuple(
            self._iter_cached_rows(symbol, timeframe, start_time_ns, end_time_ns)
            for symbol, timeframe in subscriptions
        )
        heap: list[tuple[int, str, str, int, int, int, dict[str, object]]] = []
        insertion_sequence = 0
        for stream_index, stream in enumerate(streams):
            row = next(stream, None)
            if row is None:
                continue
            insertion_sequence += 1
            heapq.heappush(
                heap,
                self._heap_item(row, stream_index, insertion_sequence),
            )
        while heap:
            close_time_ns = heap[0][0]
            rows: list[dict[str, object]] = []
            while heap and heap[0][0] == close_time_ns:
                _, _, _, _, stream_index, _, row = heapq.heappop(heap)
                rows.append(row)
                next_row = next(streams[stream_index], None)
                if next_row is not None:
                    insertion_sequence += 1
                    heapq.heappush(
                        heap,
                        self._heap_item(next_row, stream_index, insertion_sequence),
                    )
            rows.sort(
                key=lambda row: (
                    str(row["symbol"]),
                    str(row["timeframe"]),
                    _as_int(row["open_time_ns"]),
                )
            )
            yield BarCloseBatch(close_time_ns=close_time_ns, bars=tuple(rows))

    def _iter_cached_rows(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time_ns: int | None,
        end_time_ns: int | None,
    ) -> Iterator[dict[str, object]]:
        artifact = self._artifacts.get((symbol, timeframe))
        if artifact is None:
            raise CacheMissError(f"no cache artifact for {symbol}:{timeframe.value}")
        path = self.project_root / artifact.relative_path
        if not path.exists():
            raise CacheMissError(f"cache artifact does not exist: {path}")
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=4_096):
            rows = cast(list[dict[str, Any]], batch.to_pylist())
            for raw in rows:
                row = cast(dict[str, object], raw)
                if not bool(row["is_complete"]):
                    continue
                close_time_ns = _as_int(row["close_time_ns"])
                if start_time_ns is not None and close_time_ns < start_time_ns:
                    continue
                if end_time_ns is not None and close_time_ns >= end_time_ns:
                    return
                yield row

    @staticmethod
    def _heap_item(
        row: dict[str, object],
        stream_index: int,
        insertion_sequence: int,
    ) -> tuple[int, str, str, int, int, int, dict[str, object]]:
        return (
            _as_int(row["close_time_ns"]),
            str(row["symbol"]),
            str(row["timeframe"]),
            _as_int(row["open_time_ns"]),
            stream_index,
            insertion_sequence,
            row,
        )

    def aggregate_forming_bar(
        self,
        symbol: str,
        base_timeframe: Timeframe,
        target_timeframe: Timeframe,
        target_open_time_ns: int,
        event_time_ns: int,
    ) -> dict[str, object] | None:
        target_seconds = target_timeframe.seconds
        if target_seconds is None:
            raise ValueError("forming monthly bars require calendar-aware aggregation")
        target_close_time_ns = target_open_time_ns + target_seconds * 1_000_000_000
        effective_end = min(event_time_ns, target_close_time_ns)
        frame = (
            self.scan(symbol, base_timeframe, complete_only=True)
            .filter(
                (pl.col("open_time_ns") >= target_open_time_ns)
                & (pl.col("close_time_ns") <= effective_end)
            )
            .sort("open_time_ns")
            .collect()
        )
        if frame.is_empty():
            return None
        return {
            "symbol": symbol,
            "timeframe": target_timeframe.value,
            "open_time_ns": target_open_time_ns,
            "close_time_ns": target_close_time_ns,
            "open_ticks": int(frame["open_ticks"][0]),
            "high_ticks": _as_int(frame["high_ticks"].max()),
            "low_ticks": _as_int(frame["low_ticks"].min()),
            "close_ticks": int(frame["close_ticks"][-1]),
            "tick_volume": _as_int(frame["tick_volume"].sum()),
            "real_volume": _as_int(frame["real_volume"].sum()),
            "source_spread_points": int(frame["source_spread_points"][-1]),
            "is_complete": effective_end >= target_close_time_ns,
        }

    def boundaries(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time_ns: int | None = None,
        end_time_ns: int | None = None,
    ) -> tuple[tuple[int, int], ...]:
        query = self.scan(
            symbol,
            timeframe,
            complete_only=False,
        ).select("open_time_ns", "close_time_ns")
        if start_time_ns is not None:
            query = query.filter(pl.col("close_time_ns") > start_time_ns)
        if end_time_ns is not None:
            query = query.filter(pl.col("open_time_ns") < end_time_ns)
        frame = query.sort("open_time_ns").collect()
        return tuple(
            (int(open_time_ns), int(close_time_ns))
            for open_time_ns, close_time_ns in frame.iter_rows()
        )
