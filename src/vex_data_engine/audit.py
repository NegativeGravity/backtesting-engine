from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import chain
from pathlib import Path

import pyarrow.parquet as pq

from vex_contracts.data_engine import (
    CrossTimeframeMismatch,
    CrossTimeframeReport,
    DataEngineConfig,
)
from vex_contracts.timeframes import Timeframe

_COLUMNS = (
    "open_time_ns",
    "close_time_ns",
    "open_ticks",
    "high_ticks",
    "low_ticks",
    "close_ticks",
    "tick_volume",
    "is_complete",
)
_PRICE_FIELDS = ("open_ticks", "high_ticks", "low_ticks", "close_ticks")


@dataclass(frozen=True, slots=True)
class _Bar:
    open_time_ns: int
    close_time_ns: int
    open_ticks: int
    high_ticks: int
    low_ticks: int
    close_ticks: int
    tick_volume: int


@dataclass(slots=True)
class _AuditState:
    symbol: str
    base_timeframe: Timeframe
    target_timeframe: Timeframe
    targets: list[_Bar]
    config: DataEngineConfig
    index: int = 0
    compared: int = 0
    matching: int = 0
    source_only: int = 0
    aggregate_open: int | None = None
    aggregate_high: int | None = None
    aggregate_low: int | None = None
    aggregate_close: int | None = None
    aggregate_volume: int = 0
    mismatches: list[CrossTimeframeMismatch] = field(default_factory=list)

    def skip_before(self, base_start: int) -> None:
        while self.index < len(self.targets) and self.targets[self.index].open_time_ns < base_start:
            self.index += 1

    def consume(self, bar: _Bar) -> None:
        while (
            self.index < len(self.targets)
            and self.targets[self.index].close_time_ns <= bar.open_time_ns
        ):
            self._finalize_current()
        if self.index >= len(self.targets):
            return
        target = self.targets[self.index]
        if target.open_time_ns <= bar.open_time_ns < target.close_time_ns:
            if self.aggregate_open is None:
                self.aggregate_open = bar.open_ticks
                self.aggregate_high = bar.high_ticks
                self.aggregate_low = bar.low_ticks
            else:
                if self.aggregate_high is None or self.aggregate_low is None:
                    raise RuntimeError("invalid cross-timeframe aggregation state")
                self.aggregate_high = max(self.aggregate_high, bar.high_ticks)
                self.aggregate_low = min(self.aggregate_low, bar.low_ticks)
            self.aggregate_close = bar.close_ticks
            self.aggregate_volume += bar.tick_volume

    def finalize_until(self, base_end: int) -> None:
        while self.index < len(self.targets) and self.targets[self.index].close_time_ns <= base_end:
            self._finalize_current()

    def report(self) -> CrossTimeframeReport:
        return CrossTimeframeReport(
            symbol=self.symbol,
            base_timeframe=self.base_timeframe,
            target_timeframe=self.target_timeframe,
            compared_bar_count=self.compared,
            matching_bar_count=self.matching,
            mismatching_bar_count=self.compared - self.matching,
            source_only_bar_count=self.source_only,
            aggregate_only_bar_count=0,
            mismatch_samples=tuple(self.mismatches),
        )

    def _finalize_current(self) -> None:
        target = self.targets[self.index]
        if self.aggregate_open is None:
            self.source_only += 1
        else:
            aggregate_high = self.aggregate_high
            aggregate_low = self.aggregate_low
            aggregate_close = self.aggregate_close
            if aggregate_high is None or aggregate_low is None or aggregate_close is None:
                raise RuntimeError("invalid cross-timeframe aggregation state")
            source = {
                "open_ticks": target.open_ticks,
                "high_ticks": target.high_ticks,
                "low_ticks": target.low_ticks,
                "close_ticks": target.close_ticks,
                "tick_volume": target.tick_volume,
            }
            aggregate = {
                "open_ticks": self.aggregate_open,
                "high_ticks": aggregate_high,
                "low_ticks": aggregate_low,
                "close_ticks": aggregate_close,
                "tick_volume": self.aggregate_volume,
            }
            fields = [*_PRICE_FIELDS]
            if self.config.compare_tick_volume:
                fields.append("tick_volume")
            different = tuple(
                field
                for field in fields
                if abs(source[field] - aggregate[field])
                > (self.config.price_tolerance_ticks if field in _PRICE_FIELDS else 0)
            )
            self.compared += 1
            if not different:
                self.matching += 1
            elif len(self.mismatches) < self.config.max_issue_samples:
                self.mismatches.append(
                    CrossTimeframeMismatch(
                        open_time_ns=target.open_time_ns,
                        fields=different,
                        source_values={field: source[field] for field in different},
                        aggregated_values={field: aggregate[field] for field in different},
                    )
                )
        self.index += 1
        self.aggregate_open = None
        self.aggregate_high = None
        self.aggregate_low = None
        self.aggregate_close = None
        self.aggregate_volume = 0


def _iter_complete_bars(path: Path, batch_size: int) -> Iterator[_Bar]:
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=batch_size, columns=list(_COLUMNS)):
        columns = [batch.column(index).to_pylist() for index in range(len(_COLUMNS))]
        for index in range(batch.num_rows):
            if not bool(columns[7][index]):
                continue
            yield _Bar(
                open_time_ns=int(columns[0][index]),
                close_time_ns=int(columns[1][index]),
                open_ticks=int(columns[2][index]),
                high_ticks=int(columns[3][index]),
                low_ticks=int(columns[4][index]),
                close_ticks=int(columns[5][index]),
                tick_volume=int(columns[6][index]),
            )


def audit_cross_timeframe_group_files(
    symbol: str,
    base_timeframe: Timeframe,
    base_path: Path,
    target_paths: dict[Timeframe, Path],
    config: DataEngineConfig,
) -> tuple[CrossTimeframeReport, ...]:
    states = [
        _AuditState(
            symbol=symbol,
            base_timeframe=base_timeframe,
            target_timeframe=timeframe,
            targets=list(_iter_complete_bars(path, config.csv_batch_rows)),
            config=config,
        )
        for timeframe, path in target_paths.items()
    ]
    base_iterator = _iter_complete_bars(base_path, config.csv_batch_rows)
    try:
        first_base = next(base_iterator)
    except StopIteration:
        return tuple(
            CrossTimeframeReport(
                symbol=symbol,
                base_timeframe=base_timeframe,
                target_timeframe=state.target_timeframe,
                compared_bar_count=0,
                matching_bar_count=0,
                mismatching_bar_count=0,
                source_only_bar_count=len(state.targets),
                aggregate_only_bar_count=0,
            )
            for state in states
        )

    for state in states:
        state.skip_before(first_base.open_time_ns)
    last_base_close = first_base.close_time_ns
    for base_bar in chain((first_base,), base_iterator):
        last_base_close = base_bar.close_time_ns
        for state in states:
            state.consume(base_bar)
    for state in states:
        state.finalize_until(last_base_close)
    return tuple(state.report() for state in states)


def audit_cross_timeframe_files(
    symbol: str,
    base_timeframe: Timeframe,
    target_timeframe: Timeframe,
    base_path: Path,
    target_path: Path,
    config: DataEngineConfig,
) -> CrossTimeframeReport:
    return audit_cross_timeframe_group_files(
        symbol,
        base_timeframe,
        base_path,
        {target_timeframe: target_path},
        config,
    )[0]
