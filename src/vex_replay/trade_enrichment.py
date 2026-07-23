from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from vex_contracts.positions import Trade
from vex_contracts.run import BacktestRunConfig
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.catalog import ParquetBarStore

DEFAULT_POST_EXIT_HORIZONS = (4, 16, 32, 96)
PARQUET_BATCH_SIZE = 65_536
PARQUET_ROW_GROUP_SIZE = 131_072


@dataclass(slots=True)
class _TradeAnalysis:
    trade: Trade
    entry_sequence: int | None = None
    exit_sequence: int | None = None
    entry_bar_open_time_ns: int | None = None
    entry_bar_close_time_ns: int | None = None
    exit_bar_open_time_ns: int | None = None
    exit_bar_close_time_ns: int | None = None
    post_exit_bars_observed: int = 0
    post_exit_favorable_ticks: Decimal = Decimal("0")
    post_exit_adverse_ticks: Decimal = Decimal("0")
    bars_to_recover_entry: int | None = None
    bars_to_original_target: int | None = None
    horizon_snapshots: dict[int, dict[str, int | bool | Decimal | None]] = field(
        default_factory=dict
    )

    def snapshot(self, horizon: int) -> None:
        self.horizon_snapshots[horizon] = {
            "observed_bars": min(self.post_exit_bars_observed, horizon),
            "favorable_ticks": self.post_exit_favorable_ticks,
            "adverse_ticks": self.post_exit_adverse_ticks,
            "recovered_entry": (
                self.bars_to_recover_entry is not None
                and self.bars_to_recover_entry <= horizon
            ),
            "reached_original_target": (
                self.bars_to_original_target is not None
                and self.bars_to_original_target <= horizon
            ),
            "bars_to_recover_entry": (
                self.bars_to_recover_entry
                if self.bars_to_recover_entry is not None
                and self.bars_to_recover_entry <= horizon
                else None
            ),
            "bars_to_original_target": (
                self.bars_to_original_target
                if self.bars_to_original_target is not None
                and self.bars_to_original_target <= horizon
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class TradeEnrichmentResult:
    root: Path
    trades_csv: Path
    trades_parquet: Path
    candle_trade_map: Path
    summary_json: Path
    manifest_json: Path
    execution_dataset: Path | None
    market_datasets: tuple[Path, ...]


class _CandleTradeMapWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.temporary_path = path.with_suffix(path.suffix + ".tmp")
        self.temporary_path.unlink(missing_ok=True)
        self.schema = pa.schema(
            [
                pa.field("run_id", pa.string(), nullable=False),
                pa.field("strategy_id", pa.string(), nullable=False),
                pa.field("symbol", pa.string(), nullable=False),
                pa.field("timeframe", pa.string(), nullable=False),
                pa.field("sequence", pa.int64(), nullable=False),
                pa.field("open_time_ns", pa.int64(), nullable=False),
                pa.field("close_time_ns", pa.int64(), nullable=False),
                pa.field("trade_id", pa.string(), nullable=False),
                pa.field("position_id", pa.string(), nullable=False),
                pa.field("side", pa.string(), nullable=False),
                pa.field("chain_id", pa.string(), nullable=True),
                pa.field("trade_date", pa.string(), nullable=True),
                pa.field("leg", pa.string(), nullable=True),
                pa.field("state", pa.string(), nullable=False),
                pa.field("is_entry_candle", pa.bool_(), nullable=False),
                pa.field("is_exit_candle", pa.bool_(), nullable=False),
                pa.field("entry_price_ticks", pa.float64(), nullable=False),
                pa.field("final_exit_price_ticks", pa.float64(), nullable=False),
                pa.field("stop_loss_ticks", pa.int64(), nullable=True),
                pa.field("take_profit_ticks", pa.int64(), nullable=True),
                pa.field("volume_lots", pa.float64(), nullable=False),
                pa.field("final_net_pnl", pa.float64(), nullable=False),
                pa.field("final_exit_reason", pa.string(), nullable=False),
                pa.field("contains_post_hoc_outcome", pa.bool_(), nullable=False),
            ]
        )
        self._writer = pq.ParquetWriter(
            self.temporary_path,
            self.schema,
            compression="zstd",
            compression_level=6,
            write_statistics=True,
            use_dictionary=True,
        )
        self._columns: dict[str, list[Any]] = {
            field.name: [] for field in self.schema
        }
        self.row_count = 0
        self._closed = False

    def append(
        self,
        *,
        run_id: str,
        strategy_id: str,
        symbol: str,
        timeframe: str,
        sequence: int,
        open_time_ns: int,
        close_time_ns: int,
        trade: Trade,
        is_entry: bool,
        is_exit: bool,
    ) -> None:
        if is_entry and is_exit:
            state = "ENTRY_EXIT"
        elif is_entry:
            state = "ENTRY"
        elif is_exit:
            state = "EXIT"
        else:
            state = "OPEN"
        tags = trade.entry_tags
        values: dict[str, Any] = {
            "run_id": run_id,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "sequence": sequence,
            "open_time_ns": open_time_ns,
            "close_time_ns": close_time_ns,
            "trade_id": trade.trade_id,
            "position_id": trade.position_id,
            "side": trade.side.value,
            "chain_id": tags.get("chain_id"),
            "trade_date": tags.get("trade_date"),
            "leg": tags.get("leg"),
            "state": state,
            "is_entry_candle": is_entry,
            "is_exit_candle": is_exit,
            "entry_price_ticks": float(trade.entry_price_ticks),
            "final_exit_price_ticks": float(trade.exit_price_ticks),
            "stop_loss_ticks": trade.stop_loss_ticks,
            "take_profit_ticks": trade.take_profit_ticks,
            "volume_lots": float(trade.volume_lots),
            "final_net_pnl": float(trade.net_pnl),
            "final_exit_reason": trade.exit_reason,
            "contains_post_hoc_outcome": True,
        }
        for key, value in values.items():
            self._columns[key].append(value)
        self.row_count += 1
        if len(self._columns["trade_id"]) >= PARQUET_BATCH_SIZE:
            self.flush()

    def flush(self) -> None:
        count = len(self._columns["trade_id"])
        if count == 0:
            return
        arrays = [
            pa.array(self._columns[field.name], type=field.type)
            for field in self.schema
        ]
        self._writer.write_table(
            pa.Table.from_arrays(arrays, schema=self.schema),
            row_group_size=PARQUET_ROW_GROUP_SIZE,
        )
        for values in self._columns.values():
            values.clear()

    def close(self) -> None:
        if self._closed:
            return
        self.flush()
        self._writer.close()
        self._closed = True
        os.replace(self.temporary_path, self.path)

    def abort(self) -> None:
        try:
            if not self._closed:
                self._writer.close()
                self._closed = True
        finally:
            self.temporary_path.unlink(missing_ok=True)


class TradeDatasetExporter:
    def __init__(
        self,
        *,
        project_root: Path,
        bundle_root: Path,
        run: BacktestRunConfig,
        descriptor: StrategyDescriptor,
        store: ParquetBarStore,
        profiles: dict[str, SymbolProfile],
        trades: tuple[Trade, ...],
        analysis_end_time_ns: int | None = None,
        post_exit_horizons: tuple[int, ...] = DEFAULT_POST_EXIT_HORIZONS,
    ) -> None:
        self.project_root = project_root.resolve()
        self.bundle_root = bundle_root.resolve()
        self.run = run
        self.descriptor = descriptor
        self.store = store
        self.profiles = profiles
        self.trades = tuple(
            sorted(trades, key=lambda item: (item.entry_time_ns, item.exit_time_ns, item.trade_id))
        )
        horizons = tuple(sorted(set(post_exit_horizons)))
        if not horizons or any(value <= 0 for value in horizons):
            raise ValueError("post_exit_horizons must contain positive integers")
        self.horizons = horizons
        self.analysis = {trade.trade_id: _TradeAnalysis(trade) for trade in self.trades}
        self.artifacts = {
            (file_report.symbol, file_report.timeframe): file_report.artifact
            for file_report in self.store.report.files
            if file_report.artifact is not None
        }
        missing_profiles = sorted({trade.symbol for trade in self.trades} - set(self.profiles))
        if missing_profiles:
            joined = ", ".join(missing_profiles)
            raise ValueError(f"missing symbol profiles for trade symbols: {joined}")
        self.run_start_ns = _datetime_to_ns(self.run.start_time)
        configured_end_ns = _datetime_to_ns(self.run.end_time)
        configured_last_ns = configured_end_ns - 1
        self.run_end_ns = (
            min(configured_last_ns, analysis_end_time_ns)
            if analysis_end_time_ns is not None
            else configured_last_ns
        )
        if self.run_end_ns < self.run_start_ns:
            raise ValueError("analysis_end_time_ns must be after the run start")

    def export(self) -> TradeEnrichmentResult:
        output_root = self.bundle_root / "trade-analysis"
        temporary_root = self.bundle_root / ".trade-analysis.tmp"
        shutil.rmtree(temporary_root, ignore_errors=True)
        temporary_root.mkdir(parents=True, exist_ok=True)
        market_root = temporary_root / "market-with-trades"
        market_root.mkdir(parents=True, exist_ok=True)
        map_path = temporary_root / "candle-trade-map.parquet"
        map_writer = _CandleTradeMapWriter(map_path)
        market_paths: list[Path] = []
        execution_path: Path | None = None
        execution_symbols = sorted(
            {
                subscription.symbol
                for subscription in self.run.subscriptions
                if subscription.timeframe is self.run.execution_timeframe
            }
        )
        execution_symbol = execution_symbols[0] if execution_symbols else None
        dataset_rows: dict[str, int] = {}

        try:
            for symbol, timeframe in self.store.available():
                output_path = market_root / f"{_safe_name(symbol)}_{timeframe.value}.parquet"
                row_count = self._export_market_dataset(
                    symbol,
                    timeframe,
                    output_path,
                    map_writer if timeframe is self.run.execution_timeframe else None,
                )
                market_paths.append(output_path)
                dataset_rows[f"{symbol}:{timeframe.value}"] = row_count
                if symbol == execution_symbol and timeframe is self.run.execution_timeframe:
                    execution_path = output_path
            map_writer.close()

            for item in self.analysis.values():
                for horizon in self.horizons:
                    if horizon not in item.horizon_snapshots:
                        item.snapshot(horizon)

            rows = [self._trade_row(item) for item in self.analysis.values()]
            rows.sort(key=lambda item: (int(item["entry_time_ns"]), str(item["trade_id"])))
            trades_csv = temporary_root / "trades.csv"
            trades_parquet = temporary_root / "trades.parquet"
            self._write_trades_csv(trades_csv, rows)
            self._write_trades_parquet(trades_parquet, rows)
            summary = self._summary(rows, dataset_rows, map_writer.row_count)
            summary_path = temporary_root / "summary.json"
            _atomic_write_json(summary_path, summary)

            final_market_paths = tuple(
                output_root / path.relative_to(temporary_root) for path in market_paths
            )
            final_execution_path = (
                output_root / execution_path.relative_to(temporary_root)
                if execution_path is not None
                else None
            )
            final_trades_csv = output_root / "trades.csv"
            final_trades_parquet = output_root / "trades.parquet"
            final_map_path = output_root / "candle-trade-map.parquet"
            final_summary_path = output_root / "summary.json"
            manifest = {
                "schema_version": "1.0.0",
                "run_id": self.run.run_id,
                "strategy_id": self.descriptor.strategy_id,
                "dataset_id": self.run.dataset.dataset_id,
                "dataset_version": self.run.dataset.version,
                "generated_at": datetime.now(UTC).isoformat(),
                "source_dataset_immutable": True,
                "full_source_rows_preserved": True,
                "post_exit_horizons_bars": list(self.horizons),
                "analysis_start_time_ns": self.run_start_ns,
                "analysis_end_time_ns": self.run_end_ns,
                "files": {
                    "trades_csv": _relative(final_trades_csv, self.project_root),
                    "trades_parquet": _relative(final_trades_parquet, self.project_root),
                    "candle_trade_map": _relative(final_map_path, self.project_root),
                    "summary": _relative(final_summary_path, self.project_root),
                    "execution_dataset": (
                        _relative(final_execution_path, self.project_root)
                        if final_execution_path is not None
                        else None
                    ),
                    "market_datasets": [
                        _relative(path, self.project_root) for path in final_market_paths
                    ],
                },
                "sizes_bytes": {
                    _relative(
                        output_root / path.relative_to(temporary_root),
                        self.project_root,
                    ): path.stat().st_size
                    for path in [
                        trades_csv,
                        trades_parquet,
                        map_path,
                        summary_path,
                        *market_paths,
                    ]
                },
                "sha256": {
                    _relative(
                        output_root / path.relative_to(temporary_root),
                        self.project_root,
                    ): _sha256(path)
                    for path in [trades_csv, trades_parquet, summary_path]
                },
            }
            manifest_path = temporary_root / "manifest.json"
            _atomic_write_json(manifest_path, manifest)

            shutil.rmtree(output_root, ignore_errors=True)
            os.replace(temporary_root, output_root)
        except BaseException:
            map_writer.abort()
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise

        return TradeEnrichmentResult(
            root=output_root,
            trades_csv=output_root / "trades.csv",
            trades_parquet=output_root / "trades.parquet",
            candle_trade_map=output_root / "candle-trade-map.parquet",
            summary_json=output_root / "summary.json",
            manifest_json=output_root / "manifest.json",
            execution_dataset=final_execution_path,
            market_datasets=final_market_paths,
        )

    def _export_market_dataset(
        self,
        symbol: str,
        timeframe: Timeframe,
        output_path: Path,
        map_writer: _CandleTradeMapWriter | None,
    ) -> int:
        artifact = self.artifacts.get((symbol, timeframe))
        if artifact is None:
            raise ValueError(f"missing source artifact for {symbol}:{timeframe.value}")
        source_path = self.project_root / artifact.relative_path
        parquet = pq.ParquetFile(source_path, memory_map=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        extra_schema = pa.schema(
            [
                pa.field("backtest_run_id", pa.string(), nullable=False),
                pa.field("strategy_id", pa.string(), nullable=False),
                pa.field("has_trade_activity", pa.bool_(), nullable=False),
                pa.field("active_trade_count", pa.int32(), nullable=False),
                pa.field("active_long_trade_count", pa.int32(), nullable=False),
                pa.field("active_short_trade_count", pa.int32(), nullable=False),
                pa.field("entry_trade_count", pa.int32(), nullable=False),
                pa.field("exit_trade_count", pa.int32(), nullable=False),
                pa.field("stop_exit_count", pa.int32(), nullable=False),
                pa.field("target_exit_count", pa.int32(), nullable=False),
                pa.field("active_trade_ids", pa.list_(pa.string()), nullable=False),
                pa.field("active_long_trade_ids", pa.list_(pa.string()), nullable=False),
                pa.field("active_short_trade_ids", pa.list_(pa.string()), nullable=False),
                pa.field("entry_trade_ids", pa.list_(pa.string()), nullable=False),
                pa.field("exit_trade_ids", pa.list_(pa.string()), nullable=False),
                pa.field("realized_net_pnl", pa.float64(), nullable=False),
                pa.field("active_net_volume_lots", pa.float64(), nullable=False),
            ]
        )
        collisions = sorted(set(parquet.schema_arrow.names) & set(extra_schema.names))
        if collisions:
            joined = ", ".join(collisions)
            raise ValueError(
                f"source dataset already contains reserved enrichment columns: {joined}"
            )
        metadata = dict(parquet.schema_arrow.metadata or {})
        metadata.update(
            {
                b"vex.enrichment.schema_version": b"1.0.0",
                b"vex.enrichment.run_id": self.run.run_id.encode("utf-8"),
                b"vex.enrichment.strategy_id": self.descriptor.strategy_id.encode(
                    "utf-8"
                ),
                b"vex.enrichment.source_immutable": b"true",
                b"vex.enrichment.post_hoc_labels": b"true",
            }
        )
        output_schema = pa.schema(
            [*parquet.schema_arrow, *extra_schema],
            metadata=metadata,
        )
        temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary_path.unlink(missing_ok=True)
        writer = pq.ParquetWriter(
            temporary_path,
            output_schema,
            compression="zstd",
            compression_level=6,
            write_statistics=True,
            use_dictionary=True,
        )
        symbol_trades = tuple(trade for trade in self.trades if trade.symbol == symbol)
        entries = tuple(sorted(symbol_trades, key=lambda item: (item.entry_time_ns, item.trade_id)))
        exits = tuple(sorted(symbol_trades, key=lambda item: (item.exit_time_ns, item.trade_id)))
        active: dict[str, Trade] = {}
        active_sorted: tuple[Trade, ...] = ()
        active_ids_cache: tuple[str, ...] = ()
        active_long_ids_cache: tuple[str, ...] = ()
        active_short_ids_cache: tuple[str, ...] = ()
        active_net_volume_cache = Decimal("0")
        active_dirty = False
        add_index = 0
        remove_index = 0
        entry_event_index = 0
        exit_event_index = 0
        previous_close_ns: int | None = None
        row_count = 0
        post_exit_active: dict[str, _TradeAnalysis] = {}

        try:
            for batch in parquet.iter_batches(
                batch_size=PARQUET_BATCH_SIZE,
                use_threads=True,
            ):
                open_times = batch.column(
                    batch.schema.get_field_index("open_time_ns")
                ).to_pylist()
                close_times = batch.column(
                    batch.schema.get_field_index("close_time_ns")
                ).to_pylist()
                sequences = batch.column(batch.schema.get_field_index("sequence")).to_pylist()
                highs = batch.column(batch.schema.get_field_index("high_ticks")).to_pylist()
                lows = batch.column(batch.schema.get_field_index("low_ticks")).to_pylist()
                active_ids_column: list[list[str]] = []
                active_long_ids_column: list[list[str]] = []
                active_short_ids_column: list[list[str]] = []
                entry_ids_column: list[list[str]] = []
                exit_ids_column: list[list[str]] = []
                has_activity_column: list[bool] = []
                active_count_column: list[int] = []
                active_long_count_column: list[int] = []
                active_short_count_column: list[int] = []
                entry_count_column: list[int] = []
                exit_count_column: list[int] = []
                stop_exit_count_column: list[int] = []
                target_exit_count_column: list[int] = []
                realized_pnl_column: list[float] = []
                active_net_volume_column: list[float] = []

                for index in range(batch.num_rows):
                    open_time_ns = int(open_times[index])
                    close_time_ns = int(close_times[index])
                    sequence = int(sequences[index])
                    high_ticks = int(highs[index])
                    low_ticks = int(lows[index])
                    lower_bound = (
                        previous_close_ns
                        if previous_close_ns is not None
                        else open_time_ns - 1
                    )

                    if (
                        timeframe is self.run.execution_timeframe
                        and close_time_ns <= self.run_end_ns
                    ):
                        self._update_post_exit_states(
                            post_exit_active,
                            sequence,
                            high_ticks,
                            low_ticks,
                        )

                    while (
                        remove_index < len(exits)
                        and exits[remove_index].exit_time_ns <= lower_bound
                    ):
                        removed = active.pop(exits[remove_index].trade_id, None)
                        active_dirty = active_dirty or removed is not None
                        remove_index += 1
                    while (
                        add_index < len(entries)
                        and entries[add_index].entry_time_ns <= close_time_ns
                    ):
                        trade = entries[add_index]
                        active[trade.trade_id] = trade
                        active_dirty = True
                        add_index += 1

                    entry_events: list[Trade] = []
                    while (
                        entry_event_index < len(entries)
                        and entries[entry_event_index].entry_time_ns <= close_time_ns
                    ):
                        trade = entries[entry_event_index]
                        if trade.entry_time_ns > lower_bound:
                            entry_events.append(trade)
                            if timeframe is self.run.execution_timeframe:
                                item = self.analysis[trade.trade_id]
                                item.entry_sequence = sequence
                                item.entry_bar_open_time_ns = open_time_ns
                                item.entry_bar_close_time_ns = close_time_ns
                        entry_event_index += 1

                    exit_events: list[Trade] = []
                    while (
                        exit_event_index < len(exits)
                        and exits[exit_event_index].exit_time_ns <= close_time_ns
                    ):
                        trade = exits[exit_event_index]
                        if trade.exit_time_ns > lower_bound:
                            exit_events.append(trade)
                            if timeframe is self.run.execution_timeframe:
                                item = self.analysis[trade.trade_id]
                                item.exit_sequence = sequence
                                item.exit_bar_open_time_ns = open_time_ns
                                item.exit_bar_close_time_ns = close_time_ns
                                if trade.exit_time_ns <= self.run_end_ns:
                                    post_exit_active[trade.trade_id] = item
                        exit_event_index += 1

                    if active_dirty:
                        active_sorted = tuple(
                            sorted(
                                active.values(),
                                key=lambda item: (item.entry_time_ns, item.trade_id),
                            )
                        )
                        active_ids_cache = tuple(
                            trade.trade_id for trade in active_sorted
                        )
                        active_long_ids_cache = tuple(
                            trade.trade_id
                            for trade in active_sorted
                            if trade.side.value == "long"
                        )
                        active_short_ids_cache = tuple(
                            trade.trade_id
                            for trade in active_sorted
                            if trade.side.value == "short"
                        )
                        active_net_volume_cache = sum(
                            (
                                trade.volume_lots
                                if trade.side.value == "long"
                                else -trade.volume_lots
                                for trade in active_sorted
                            ),
                            start=Decimal("0"),
                        )
                        active_dirty = False
                    visible = active_sorted
                    entry_ids = [trade.trade_id for trade in entry_events]
                    exit_ids = [trade.trade_id for trade in exit_events]
                    stop_exits = sum(
                        trade.exit_reason == "stop_loss" for trade in exit_events
                    )
                    target_exits = sum(
                        trade.exit_reason == "take_profit" for trade in exit_events
                    )
                    realized_pnl = sum(
                        (trade.net_pnl for trade in exit_events),
                        start=Decimal("0"),
                    )

                    active_ids_column.append(active_ids_cache)
                    active_long_ids_column.append(active_long_ids_cache)
                    active_short_ids_column.append(active_short_ids_cache)
                    entry_ids_column.append(entry_ids)
                    exit_ids_column.append(exit_ids)
                    has_activity_column.append(bool(visible or entry_events or exit_events))
                    active_count_column.append(len(active_ids_cache))
                    active_long_count_column.append(len(active_long_ids_cache))
                    active_short_count_column.append(len(active_short_ids_cache))
                    entry_count_column.append(len(entry_events))
                    exit_count_column.append(len(exit_events))
                    stop_exit_count_column.append(stop_exits)
                    target_exit_count_column.append(target_exits)
                    realized_pnl_column.append(float(realized_pnl))
                    active_net_volume_column.append(float(active_net_volume_cache))

                    if map_writer is not None:
                        entry_set = set(entry_ids)
                        exit_set = set(exit_ids)
                        for trade in visible:
                            map_writer.append(
                                run_id=self.run.run_id,
                                strategy_id=self.descriptor.strategy_id,
                                symbol=symbol,
                                timeframe=timeframe.value,
                                sequence=sequence,
                                open_time_ns=open_time_ns,
                                close_time_ns=close_time_ns,
                                trade=trade,
                                is_entry=trade.trade_id in entry_set,
                                is_exit=trade.trade_id in exit_set,
                            )

                    previous_close_ns = close_time_ns
                    row_count += 1

                extra_arrays = [
                    pa.array([self.run.run_id] * batch.num_rows, type=pa.string()),
                    pa.array([self.descriptor.strategy_id] * batch.num_rows, type=pa.string()),
                    pa.array(has_activity_column, type=pa.bool_()),
                    pa.array(active_count_column, type=pa.int32()),
                    pa.array(active_long_count_column, type=pa.int32()),
                    pa.array(active_short_count_column, type=pa.int32()),
                    pa.array(entry_count_column, type=pa.int32()),
                    pa.array(exit_count_column, type=pa.int32()),
                    pa.array(stop_exit_count_column, type=pa.int32()),
                    pa.array(target_exit_count_column, type=pa.int32()),
                    pa.array(active_ids_column, type=pa.list_(pa.string())),
                    pa.array(active_long_ids_column, type=pa.list_(pa.string())),
                    pa.array(active_short_ids_column, type=pa.list_(pa.string())),
                    pa.array(entry_ids_column, type=pa.list_(pa.string())),
                    pa.array(exit_ids_column, type=pa.list_(pa.string())),
                    pa.array(realized_pnl_column, type=pa.float64()),
                    pa.array(active_net_volume_column, type=pa.float64()),
                ]
                table = pa.Table.from_arrays(
                    [*batch.columns, *extra_arrays],
                    schema=output_schema,
                )
                writer.write_table(table, row_group_size=PARQUET_ROW_GROUP_SIZE)
        except BaseException:
            writer.close()
            temporary_path.unlink(missing_ok=True)
            raise
        else:
            writer.close()
            if row_count != artifact.row_count:
                temporary_path.unlink(missing_ok=True)
                raise ValueError(
                    f"row-count mismatch for {symbol}:{timeframe.value}; "
                    f"source={artifact.row_count}, enriched={row_count}"
                )
            os.replace(temporary_path, output_path)
        return row_count

    def _update_post_exit_states(
        self,
        states: dict[str, _TradeAnalysis],
        sequence: int,
        high_ticks: int,
        low_ticks: int,
    ) -> None:
        completed: list[str] = []
        max_horizon = self.horizons[-1]
        for trade_id, item in states.items():
            if item.exit_sequence is None or sequence <= item.exit_sequence:
                continue
            item.post_exit_bars_observed += 1
            trade = item.trade
            exit_ticks = trade.exit_price_ticks
            entry_ticks = trade.entry_price_ticks
            if trade.side.value == "long":
                favorable = max(Decimal("0"), Decimal(high_ticks) - exit_ticks)
                adverse = max(Decimal("0"), exit_ticks - Decimal(low_ticks))
                recovered = Decimal(high_ticks) >= entry_ticks
                target_reached = (
                    trade.take_profit_ticks is not None
                    and high_ticks >= trade.take_profit_ticks
                )
            else:
                favorable = max(Decimal("0"), exit_ticks - Decimal(low_ticks))
                adverse = max(Decimal("0"), Decimal(high_ticks) - exit_ticks)
                recovered = Decimal(low_ticks) <= entry_ticks
                target_reached = (
                    trade.take_profit_ticks is not None
                    and low_ticks <= trade.take_profit_ticks
                )
            item.post_exit_favorable_ticks = max(item.post_exit_favorable_ticks, favorable)
            item.post_exit_adverse_ticks = max(item.post_exit_adverse_ticks, adverse)
            if recovered and item.bars_to_recover_entry is None:
                item.bars_to_recover_entry = item.post_exit_bars_observed
            if target_reached and item.bars_to_original_target is None:
                item.bars_to_original_target = item.post_exit_bars_observed
            if item.post_exit_bars_observed in self.horizons:
                item.snapshot(item.post_exit_bars_observed)
            if item.post_exit_bars_observed >= max_horizon:
                completed.append(trade_id)
        for trade_id in completed:
            states.pop(trade_id, None)

    def _trade_row(self, item: _TradeAnalysis) -> dict[str, Any]:
        trade = item.trade
        profile = self.profiles[trade.symbol]
        tick_size = profile.trade_tick_size
        risk_ticks = (
            abs(Decimal(trade.stop_loss_ticks) - trade.entry_price_ticks)
            if trade.stop_loss_ticks is not None
            else None
        )
        duration_bars = (
            item.exit_sequence - item.entry_sequence + 1
            if item.entry_sequence is not None and item.exit_sequence is not None
            else None
        )
        outcome = "WIN" if trade.net_pnl > 0 else "LOSS" if trade.net_pnl < 0 else "BREAKEVEN"
        row: dict[str, Any] = {
            "run_id": trade.run_id,
            "strategy_id": self.descriptor.strategy_id,
            "strategy_instance_id": trade.strategy_instance_id,
            "trade_id": trade.trade_id,
            "position_id": trade.position_id,
            "entry_order_id": trade.entry_order_id,
            "entry_client_order_id": trade.entry_client_order_id,
            "symbol": trade.symbol,
            "side": trade.side.value,
            "chain_id": trade.entry_tags.get("chain_id"),
            "trade_date": trade.entry_tags.get("trade_date"),
            "leg": trade.entry_tags.get("leg"),
            "entry_time_ns": trade.entry_time_ns,
            "entry_time_utc": _iso_ns(trade.entry_time_ns),
            "entry_sequence": item.entry_sequence,
            "entry_bar_open_time_ns": item.entry_bar_open_time_ns,
            "entry_bar_close_time_ns": item.entry_bar_close_time_ns,
            "entry_price_ticks": str(trade.entry_price_ticks),
            "entry_price": str(trade.entry_price_ticks * tick_size),
            "exit_time_ns": trade.exit_time_ns,
            "exit_time_utc": _iso_ns(trade.exit_time_ns),
            "exit_sequence": item.exit_sequence,
            "exit_bar_open_time_ns": item.exit_bar_open_time_ns,
            "exit_bar_close_time_ns": item.exit_bar_close_time_ns,
            "exit_price_ticks": str(trade.exit_price_ticks),
            "exit_price": str(trade.exit_price_ticks * tick_size),
            "duration_ns": trade.exit_time_ns - trade.entry_time_ns,
            "duration_seconds": (trade.exit_time_ns - trade.entry_time_ns) / 1_000_000_000,
            "duration_bars": duration_bars,
            "volume_lots": str(trade.volume_lots),
            "stop_loss_ticks": trade.stop_loss_ticks,
            "stop_loss_price": (
                str(Decimal(trade.stop_loss_ticks) * tick_size)
                if trade.stop_loss_ticks is not None
                else None
            ),
            "take_profit_ticks": trade.take_profit_ticks,
            "take_profit_price": (
                str(Decimal(trade.take_profit_ticks) * tick_size)
                if trade.take_profit_ticks is not None
                else None
            ),
            "risk_ticks": str(risk_ticks) if risk_ticks is not None else None,
            "exit_reason": trade.exit_reason,
            "outcome": outcome,
            "is_stop_loss": trade.exit_reason == "stop_loss",
            "is_take_profit": trade.exit_reason == "take_profit",
            "gross_pnl": str(trade.gross_pnl),
            "commission": str(trade.commission),
            "spread_cost": str(trade.spread_cost),
            "slippage_cost": str(trade.slippage_cost),
            "swap": str(trade.swap),
            "net_pnl": str(trade.net_pnl),
            "initial_risk": str(trade.initial_risk) if trade.initial_risk is not None else None,
            "realized_r_multiple": (
                str(trade.realized_r_multiple)
                if trade.realized_r_multiple is not None
                else None
            ),
            "mae_money": str(trade.mae),
            "mfe_money": str(trade.mfe),
            "mae_r": (
                str(trade.mae / trade.initial_risk)
                if trade.initial_risk is not None
                else None
            ),
            "mfe_r": (
                str(trade.mfe / trade.initial_risk)
                if trade.initial_risk is not None
                else None
            ),
            "intrabar_ambiguous": trade.intrabar_ambiguous,
            "entry_tags_json": json.dumps(trade.entry_tags, ensure_ascii=False, sort_keys=True),
        }
        for horizon in self.horizons:
            snapshot = item.horizon_snapshots[horizon]
            favorable_ticks = Decimal(snapshot["favorable_ticks"] or 0)
            adverse_ticks = Decimal(snapshot["adverse_ticks"] or 0)
            favorable_r = (
                favorable_ticks / risk_ticks
                if risk_ticks is not None and risk_ticks > 0
                else None
            )
            adverse_r = (
                adverse_ticks / risk_ticks
                if risk_ticks is not None and risk_ticks > 0
                else None
            )
            reached_target = bool(snapshot["reached_original_target"])
            recovered_entry = bool(snapshot["recovered_entry"])
            if trade.side.value == "long":
                favorable_extreme_ticks = trade.exit_price_ticks + favorable_ticks
                adverse_extreme_ticks = trade.exit_price_ticks - adverse_ticks
            else:
                favorable_extreme_ticks = trade.exit_price_ticks - favorable_ticks
                adverse_extreme_ticks = trade.exit_price_ticks + adverse_ticks
            if trade.exit_reason != "stop_loss":
                stop_hunt_class = "NOT_STOP_LOSS"
            elif reached_target:
                stop_hunt_class = "ORIGINAL_TARGET_REACHED"
            elif recovered_entry:
                stop_hunt_class = "ENTRY_RECOVERED"
            else:
                stop_hunt_class = "NO_RECOVERY"
            row.update(
                {
                    f"post_exit_observed_bars_{horizon}": snapshot["observed_bars"],
                    f"post_exit_original_direction_ticks_{horizon}": str(favorable_ticks),
                    f"post_exit_against_original_direction_ticks_{horizon}": str(adverse_ticks),
                    f"post_exit_original_direction_r_{horizon}": (
                        str(favorable_r) if favorable_r is not None else None
                    ),
                    f"post_exit_against_original_direction_r_{horizon}": (
                        str(adverse_r) if adverse_r is not None else None
                    ),
                    f"post_exit_original_direction_extreme_ticks_{horizon}": str(
                        favorable_extreme_ticks
                    ),
                    f"post_exit_against_original_direction_extreme_ticks_{horizon}": str(
                        adverse_extreme_ticks
                    ),
                    f"post_exit_original_direction_extreme_price_{horizon}": str(
                        favorable_extreme_ticks * tick_size
                    ),
                    f"post_exit_against_original_direction_extreme_price_{horizon}": str(
                        adverse_extreme_ticks * tick_size
                    ),
                    f"recovered_entry_after_exit_{horizon}": recovered_entry,
                    f"reached_original_target_after_exit_{horizon}": reached_target,
                    f"bars_to_recover_entry_{horizon}": snapshot["bars_to_recover_entry"],
                    f"bars_to_original_target_{horizon}": snapshot["bars_to_original_target"],
                    f"stop_hunt_recovered_entry_{horizon}": (
                        trade.exit_reason == "stop_loss" and recovered_entry
                    ),
                    f"stop_hunt_reached_original_target_{horizon}": (
                        trade.exit_reason == "stop_loss" and reached_target
                    ),
                    f"stop_hunt_class_{horizon}": stop_hunt_class,
                }
            )
        return row

    @staticmethod
    def _write_trades_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(rows[0]) if rows else [
            "run_id",
            "strategy_id",
            "trade_id",
            "position_id",
            "symbol",
            "side",
            "entry_time_ns",
            "exit_time_ns",
            "exit_reason",
            "net_pnl",
        ]
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="raise")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)

    @staticmethod
    def _write_trades_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if rows:
            table = pa.Table.from_pylist(rows)
        else:
            table = pa.table(
                {
                    "run_id": pa.array([], type=pa.string()),
                    "strategy_id": pa.array([], type=pa.string()),
                    "trade_id": pa.array([], type=pa.string()),
                    "position_id": pa.array([], type=pa.string()),
                    "symbol": pa.array([], type=pa.string()),
                    "side": pa.array([], type=pa.string()),
                    "entry_time_ns": pa.array([], type=pa.int64()),
                    "exit_time_ns": pa.array([], type=pa.int64()),
                    "exit_reason": pa.array([], type=pa.string()),
                    "net_pnl": pa.array([], type=pa.string()),
                }
            )
        temporary = path.with_suffix(path.suffix + ".tmp")
        pq.write_table(
            table,
            temporary,
            compression="zstd",
            compression_level=6,
            row_group_size=PARQUET_ROW_GROUP_SIZE,
            write_statistics=True,
            use_dictionary=True,
        )
        os.replace(temporary, path)

    def _summary(
        self,
        rows: list[dict[str, Any]],
        dataset_rows: dict[str, int],
        map_row_count: int,
    ) -> dict[str, Any]:
        stopped = [row for row in rows if bool(row["is_stop_loss"])]
        target = [row for row in rows if bool(row["is_take_profit"])]
        max_horizon = self.horizons[-1]
        recovered_key = f"stop_hunt_recovered_entry_{max_horizon}"
        target_key = f"stop_hunt_reached_original_target_{max_horizon}"
        recovered = sum(bool(row[recovered_key]) for row in stopped)
        reached_target = sum(bool(row[target_key]) for row in stopped)
        recovered_entry_only = recovered - reached_target
        no_recovery = len(stopped) - recovered
        return {
            "schema_version": "1.0.0",
            "run_id": self.run.run_id,
            "strategy_id": self.descriptor.strategy_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "analysis_start_time_ns": self.run_start_ns,
            "analysis_end_time_ns": self.run_end_ns,
            "trade_count": len(rows),
            "winning_trade_count": sum(row["outcome"] == "WIN" for row in rows),
            "losing_trade_count": sum(row["outcome"] == "LOSS" for row in rows),
            "breakeven_trade_count": sum(row["outcome"] == "BREAKEVEN" for row in rows),
            "stop_loss_trade_count": len(stopped),
            "take_profit_trade_count": len(target),
            "stop_hunt_analysis_horizon_bars": max_horizon,
            "stopped_then_recovered_entry_count": recovered,
            "stopped_then_reached_original_target_count": reached_target,
            "stopped_then_recovered_entry_only_count": recovered_entry_only,
            "stopped_without_entry_recovery_count": no_recovery,
            "stopped_then_recovered_entry_percent": (
                recovered * 100 / len(stopped) if stopped else 0.0
            ),
            "stopped_then_reached_original_target_percent": (
                reached_target * 100 / len(stopped) if stopped else 0.0
            ),
            "candle_trade_map_row_count": map_row_count,
            "market_dataset_rows": dataset_rows,
            "unmapped_entry_trade_count": sum(
                item.entry_sequence is None for item in self.analysis.values()
            ),
            "unmapped_exit_trade_count": sum(
                item.exit_sequence is None for item in self.analysis.values()
            ),
            "definitions": {
                "stop_hunt_recovered_entry": (
                    "A stop-loss trade returned to its original entry price within the horizon."
                ),
                "stop_hunt_reached_original_target": (
                    "A stop-loss trade subsequently reached its original "
                    "take-profit level within the horizon."
                ),
                "post_exit_original_direction_ticks": (
                    "Maximum move after exit in the original trade direction, "
                    "measured from the exit price."
                ),
                "post_exit_against_original_direction_ticks": (
                    "Maximum move after exit against the original trade direction, "
                    "measured from the exit price."
                ),
                "post_exit_window": (
                    "Only execution-timeframe candles processed inside the configured "
                    "backtest end time are used."
                ),
                "price_basis": (
                    "Post-exit movement uses the canonical source candle high/low "
                    "in integer trade ticks."
                ),
            },
        }


def export_trade_enriched_datasets(
    *,
    project_root: Path,
    bundle_root: Path,
    run: BacktestRunConfig,
    descriptor: StrategyDescriptor,
    store: ParquetBarStore,
    profiles: Iterable[SymbolProfile],
    trades: tuple[Trade, ...],
    analysis_end_time_ns: int | None = None,
) -> TradeEnrichmentResult:
    exporter = TradeDatasetExporter(
        project_root=project_root,
        bundle_root=bundle_root,
        run=run,
        descriptor=descriptor,
        store=store,
        profiles={profile.symbol: profile for profile in profiles},
        trades=trades,
        analysis_end_time_ns=analysis_end_time_ns,
    )
    return exporter.export()


def _safe_name(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in value
    )


def _datetime_to_ns(value: datetime) -> int:
    normalized = value.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = normalized - epoch
    return (
        delta.days * 86_400_000_000_000
        + delta.seconds * 1_000_000_000
        + delta.microseconds * 1_000
    )


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _iso_ns(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC).isoformat()
