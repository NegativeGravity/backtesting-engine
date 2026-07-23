import json
import sqlite3
import threading
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

import polars as pl
from pydantic import JsonValue

from vex_analytics.engine import AnalyticsEngine
from vex_contracts.analytics import (
    AnalyticsComparisonReport,
    AnalyticsComparisonRow,
    AnalyticsReport,
    EquityCurvePoint,
)
from vex_contracts.broker import BrokerSimulationReport
from vex_contracts.enums import EventType
from vex_contracts.orders import Fill, Order
from vex_contracts.positions import AccountSnapshot, Position, Trade
from vex_contracts.replay import (
    ReplayBar,
    ReplayBootstrap,
    ReplayBundleManifest,
    ReplayCatalog,
    ReplayMetrics,
    ReplayRunDescriptor,
    ReplayTimelineItem,
)
from vex_contracts.serialization import load_json
from vex_contracts.strategy_runtime import StrategyBacktestReport
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.catalog import ParquetBarStore


def _timeline_kind(
    value: object,
) -> Literal[
    "broker_event",
    "chart_command",
    "strategy_action",
    "strategy_log",
    "account_snapshot",
]:
    normalized = str(value)
    allowed = {
        "broker_event",
        "chart_command",
        "strategy_action",
        "strategy_log",
        "account_snapshot",
    }
    if normalized not in allowed:
        raise ValueError(f"unknown replay timeline kind: {normalized}")
    return cast(
        Literal[
            "broker_event",
            "chart_command",
            "strategy_action",
            "strategy_log",
            "account_snapshot",
        ],
        normalized,
    )


@dataclass(slots=True)
class _RunContext:
    manifest: ReplayBundleManifest
    store: ParquetBarStore
    profiles: dict[str, SymbolProfile]
    strategy_report: StrategyBacktestReport
    database_path: Path
    metrics: ReplayMetrics
    analytics_report: AnalyticsReport
    has_state_snapshots: bool
    has_terminal_orders: bool
    database_signature: tuple[int, int]


class ReplayRunNotFoundError(KeyError):
    pass


class ReplayRunRepository:
    def __init__(
        self,
        project_root: str | Path,
        runs_root: str | Path = "data/replay/runs",
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.runs_root = self.project_root / runs_root
        self._contexts: dict[str, _RunContext] = {}
        self._connections = threading.local()
        self.refresh()

    def refresh(self) -> None:
        contexts: dict[str, _RunContext] = {}
        if not self.runs_root.exists():
            self._contexts = contexts
            return
        for manifest_path in sorted(self.runs_root.glob("*/manifest.json")):
            manifest = ReplayBundleManifest.model_validate(load_json(manifest_path))
            report = StrategyBacktestReport.model_validate(
                load_json(self.project_root / manifest.strategy_report_path)
            )
            profiles_value = load_json(self.project_root / manifest.symbol_profile_paths[0])
            profiles = {
                profile.symbol: profile
                for profile in (
                    SymbolProfile.model_validate(value) for value in cast(list[Any], profiles_value)
                )
            }
            store = ParquetBarStore.from_report_path(
                self.project_root,
                self.project_root / manifest.import_report_path,
            )
            database_path = self.project_root / manifest.sqlite_path
            with sqlite3.connect(database_path) as connection:
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'metrics'"
                ).fetchone()
                if row is None:
                    raise ValueError(f"replay metrics missing for {manifest.run_id}")
                metrics = ReplayMetrics.model_validate(json.loads(str(row[0])))
                has_state_snapshots = (
                    connection.execute(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type = 'table' AND name = 'broker_state_snapshots'"
                    ).fetchone()
                    is not None
                )
                has_terminal_orders = (
                    connection.execute(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type = 'table' AND name = 'terminal_orders'"
                    ).fetchone()
                    is not None
                )
            database_stat = database_path.stat()
            analytics_path = (
                self.project_root / manifest.analytics_report_path
                if manifest.analytics_report_path is not None
                else None
            )
            if analytics_path is not None and analytics_path.exists():
                analytics_report = AnalyticsReport.model_validate(load_json(analytics_path))
            else:
                equity_curve = self._read_equity_curve(database_path, manifest.end_time_ns)
                trades = self._read_trades(database_path, manifest.end_time_ns)
                analytics_report = AnalyticsEngine().calculate(
                    run_id=manifest.run_id,
                    currency=report.broker_report.final_account.currency,
                    initial_balance=metrics.initial_balance,
                    start_time_ns=manifest.start_time_ns,
                    end_time_ns=manifest.end_time_ns,
                    trades=trades,
                    equity_curve=equity_curve,
                )
            contexts[manifest.run_id] = _RunContext(
                manifest=manifest,
                store=store,
                profiles=profiles,
                strategy_report=report,
                database_path=database_path,
                metrics=metrics,
                analytics_report=analytics_report,
                has_state_snapshots=has_state_snapshots,
                has_terminal_orders=has_terminal_orders,
                database_signature=(database_stat.st_mtime_ns, database_stat.st_size),
            )
        self._contexts = contexts

    def catalog(self) -> ReplayCatalog:
        return ReplayCatalog(
            runs=tuple(
                ReplayRunDescriptor(
                    run_id=context.manifest.run_id,
                    name=context.manifest.name,
                    strategy_id=context.manifest.strategy_id,
                    strategy_instance_id=context.manifest.strategy_instance_id,
                    dataset_id=context.manifest.dataset_id,
                    default_symbol=context.manifest.default_symbol,
                    default_timeframe=context.manifest.default_timeframe,
                    execution_timeframe=context.manifest.execution_timeframe,
                    available_symbols=context.manifest.available_symbols,
                    available_timeframes=context.manifest.available_timeframes,
                    start_time_ns=context.manifest.start_time_ns,
                    end_time_ns=context.manifest.end_time_ns,
                    metrics=context.metrics,
                )
                for context in sorted(self._contexts.values(), key=lambda item: item.manifest.name)
            )
        )

    def descriptor(self, run_id: str) -> ReplayRunDescriptor:
        context = self._context(run_id)
        manifest = context.manifest
        return ReplayRunDescriptor(
            run_id=manifest.run_id,
            name=manifest.name,
            strategy_id=manifest.strategy_id,
            strategy_instance_id=manifest.strategy_instance_id,
            dataset_id=manifest.dataset_id,
            default_symbol=manifest.default_symbol,
            default_timeframe=manifest.default_timeframe,
            execution_timeframe=manifest.execution_timeframe,
            available_symbols=manifest.available_symbols,
            available_timeframes=manifest.available_timeframes,
            start_time_ns=manifest.start_time_ns,
            end_time_ns=manifest.end_time_ns,
            metrics=context.metrics,
        )

    def first_execution_bar(self, run_id: str) -> ReplayBar:
        context = self._context(run_id)
        frame = context.store.load(
            context.manifest.default_symbol,
            context.manifest.execution_timeframe,
            context.manifest.start_time_ns,
            context.manifest.end_time_ns + 1,
            complete_only=True,
            limit=1,
        )
        if frame.is_empty():
            raise ValueError(f"run has no execution bars: {run_id}")
        return self._replay_bar(context, frame.row(0, named=True))

    def last_execution_bar(self, run_id: str) -> ReplayBar:
        context = self._context(run_id)
        frame = (
            context.store.scan(
                context.manifest.default_symbol,
                context.manifest.execution_timeframe,
                context.manifest.start_time_ns,
                context.manifest.end_time_ns + 1,
                complete_only=True,
            )
            .sort("open_time_ns", descending=True)
            .head(1)
            .collect()
        )
        if frame.is_empty():
            raise ValueError(f"run has no execution bars: {run_id}")
        return self._replay_bar(context, frame.row(0, named=True))

    def execution_bars_after(
        self,
        run_id: str,
        sequence: int,
        count: int,
    ) -> tuple[ReplayBar, ...]:
        context = self._context(run_id)
        frame = (
            context.store.scan(
                context.manifest.default_symbol,
                context.manifest.execution_timeframe,
                context.manifest.start_time_ns,
                context.manifest.end_time_ns + 1,
                complete_only=True,
            )
            .filter(pl.col("sequence") > sequence)
            .sort("sequence")
            .head(count)
            .collect()
        )
        return tuple(self._replay_bar(context, row) for row in frame.iter_rows(named=True))

    def execution_bar_before(self, run_id: str, sequence: int) -> ReplayBar | None:
        context = self._context(run_id)
        frame = (
            context.store.scan(
                context.manifest.default_symbol,
                context.manifest.execution_timeframe,
                context.manifest.start_time_ns,
                context.manifest.end_time_ns + 1,
                complete_only=True,
            )
            .filter(pl.col("sequence") < sequence)
            .sort("sequence", descending=True)
            .head(1)
            .collect()
        )
        if frame.is_empty():
            return None
        return self._replay_bar(context, frame.row(0, named=True))

    def execution_bar_at_or_before_time(self, run_id: str, time_ns: int) -> ReplayBar:
        context = self._context(run_id)
        frame = (
            context.store.scan(
                context.manifest.default_symbol,
                context.manifest.execution_timeframe,
                context.manifest.start_time_ns,
                context.manifest.end_time_ns + 1,
                complete_only=True,
            )
            .filter(pl.col("close_time_ns") <= time_ns)
            .sort("close_time_ns", descending=True)
            .head(1)
            .collect()
        )
        if frame.is_empty():
            return self.first_execution_bar(run_id)
        return self._replay_bar(context, frame.row(0, named=True))

    def bars_for_view(
        self,
        run_id: str,
        symbol: str,
        timeframe: Timeframe,
        start_exclusive_ns: int,
        end_inclusive_ns: int,
        limit: int = 5000,
    ) -> tuple[ReplayBar, ...]:
        context = self._context(run_id)
        frame = (
            context.store.scan(symbol, timeframe, complete_only=True)
            .filter(
                (pl.col("close_time_ns") > start_exclusive_ns)
                & (pl.col("close_time_ns") <= end_inclusive_ns)
            )
            .sort("close_time_ns")
            .head(limit)
            .collect()
        )
        return tuple(self._replay_bar(context, row) for row in frame.iter_rows(named=True))

    def history(
        self,
        run_id: str,
        symbol: str,
        timeframe: Timeframe,
        cursor_time_ns: int,
        count: int,
    ) -> tuple[ReplayBar, ...]:
        context = self._context(run_id)
        frame = context.store.window(symbol, timeframe, cursor_time_ns, count)
        return tuple(self._replay_bar(context, row) for row in frame.iter_rows(named=True))

    def timeline_between(
        self,
        run_id: str,
        start_exclusive_ns: int,
        end_inclusive_ns: int,
        limit: int = 10000,
    ) -> tuple[ReplayTimelineItem, ...]:
        context = self._context(run_id)
        connection = self._connection(context)
        rows = connection.execute(
            "SELECT sequence, time_ns, kind, payload FROM timeline "
            "WHERE time_ns > ? AND time_ns <= ? ORDER BY sequence LIMIT ?",
            (start_exclusive_ns, end_inclusive_ns, limit),
        ).fetchall()
        return tuple(
            ReplayTimelineItem(
                sequence=int(sequence),
                time_ns=int(time_ns),
                kind=_timeline_kind(kind),
                payload=cast(dict[str, JsonValue], json.loads(str(payload))),
            )
            for sequence, time_ns, kind, payload in rows
        )

    def timeline_until(
        self,
        run_id: str,
        end_inclusive_ns: int,
        limit: int = 10000,
    ) -> tuple[ReplayTimelineItem, ...]:
        context = self._context(run_id)
        connection = self._connection(context)
        rows = connection.execute(
            "SELECT sequence, time_ns, kind, payload FROM ("
            "SELECT sequence, time_ns, kind, payload FROM timeline "
            "WHERE time_ns <= ? ORDER BY sequence DESC LIMIT ?"
            ") ORDER BY sequence",
            (end_inclusive_ns, limit),
        ).fetchall()
        return tuple(
            ReplayTimelineItem(
                sequence=int(sequence),
                time_ns=int(time_ns),
                kind=_timeline_kind(kind),
                payload=cast(dict[str, JsonValue], json.loads(str(payload))),
            )
            for sequence, time_ns, kind, payload in rows
        )

    def timeline_for_window(
        self,
        run_id: str,
        start_exclusive_ns: int,
        end_inclusive_ns: int,
        limit: int = 10_000,
    ) -> tuple[ReplayTimelineItem, ...]:
        window = list(
            self.timeline_between(
                run_id,
                start_exclusive_ns,
                end_inclusive_ns,
                limit,
            )
        )
        seed = self.timeline_until(run_id, start_exclusive_ns, limit=2_000)
        latest_series: dict[str, ReplayTimelineItem] = {}
        for item in seed:
            if item.kind != "chart_command":
                continue
            command_type = str(item.payload.get("command_type", ""))
            if command_type == "declare_series":
                series = item.payload.get("series")
                if isinstance(series, dict):
                    series_id = str(series.get("series_id", ""))
                    if series_id:
                        latest_series[f"declare:{series_id}"] = item
            elif command_type == "set_series_visibility":
                series_id = str(item.payload.get("series_id", ""))
                if series_id:
                    latest_series[f"visibility:{series_id}"] = item
        merged = list(latest_series.values()) + window
        merged.sort(key=lambda item: item.sequence)
        return tuple(merged[-limit:])

    def account_at(self, run_id: str, time_ns: int) -> AccountSnapshot:
        context = self._context(run_id)
        connection = self._connection(context)
        row = connection.execute(
            "SELECT payload FROM account_snapshots WHERE time_ns <= ? "
            "ORDER BY time_ns DESC LIMIT 1",
            (time_ns,),
        ).fetchone()
        if row is None:
            row = connection.execute(
                "SELECT payload FROM account_snapshots ORDER BY time_ns LIMIT 1"
            ).fetchone()
        if row is None:
            return context.strategy_report.broker_report.final_account.model_copy(
                update={
                    "timestamp_ns": context.manifest.start_time_ns,
                    "sequence": 0,
                    "balance": context.metrics.initial_balance,
                    "equity": context.metrics.initial_balance,
                    "free_margin": context.metrics.initial_balance,
                    "margin": Decimal("0"),
                    "floating_pnl": Decimal("0"),
                    "peak_equity": context.metrics.initial_balance,
                    "drawdown_amount": Decimal("0"),
                    "drawdown_percent": Decimal("0"),
                }
            )
        return AccountSnapshot.model_validate(json.loads(str(row[0])))

    def state_at(
        self,
        run_id: str,
        time_ns: int,
        history_limit: int | None = None,
    ) -> tuple[tuple[Order, ...], tuple[Position, ...], tuple[Fill, ...], tuple[Trade, ...]]:
        context = self._context(run_id)
        orders: dict[str, Order] = {}
        positions: dict[str, Position] = {}
        connection = self._connection(context)
        snapshot_time_ns = context.manifest.start_time_ns - 1
        snapshot_sequence = 0
        if context.has_state_snapshots:
            snapshot_row = connection.execute(
                "SELECT time_ns, event_sequence, orders, positions "
                "FROM broker_state_snapshots WHERE time_ns <= ? "
                "ORDER BY time_ns DESC, event_sequence DESC LIMIT 1",
                (time_ns,),
            ).fetchone()
            if snapshot_row is not None:
                snapshot_time_ns = int(snapshot_row[0])
                snapshot_sequence = int(snapshot_row[1])
                orders = {
                    order.order_id: order
                    for order in (
                        Order.model_validate(value)
                        for value in cast(list[Any], json.loads(str(snapshot_row[2])))
                    )
                }
                positions = {
                    position.position_id: position
                    for position in (
                        Position.model_validate(value)
                        for value in cast(list[Any], json.loads(str(snapshot_row[3])))
                    )
                }
        rows = connection.execute(
            "SELECT event_type, payload FROM broker_events "
            "WHERE time_ns <= ? AND (time_ns > ? OR (time_ns = ? AND sequence > ?)) "
            "ORDER BY sequence",
            (time_ns, snapshot_time_ns, snapshot_time_ns, snapshot_sequence),
        ).fetchall()
        order_rows = self._terminal_order_rows(
            connection,
            context.has_terminal_orders,
            time_ns,
            history_limit,
        )
        fill_rows = self._history_entity_rows(connection, "fill", time_ns, history_limit)
        trade_rows = self._history_entity_rows(connection, "trade", time_ns, history_limit)
        for event_type_raw, envelope_raw in rows:
            envelope = cast(dict[str, Any], json.loads(str(envelope_raw)))
            payload = cast(dict[str, Any], envelope["payload"])
            event_type = EventType(str(event_type_raw))
            if (
                event_type.value.startswith("order.")
                and "order_id" in payload
                and "request" in payload
            ):
                order = Order.model_validate(
                    {key: payload[key] for key in Order.model_fields if key in payload}
                )
                orders[order.order_id] = order
            if event_type is EventType.ACCOUNT_UPDATED:
                snapshot_positions = payload.get("positions", ())
                if isinstance(snapshot_positions, list):
                    positions = {
                        position.position_id: position
                        for position in (
                            Position.model_validate(value) for value in snapshot_positions
                        )
                    }
            if event_type in {EventType.POSITION_OPENED, EventType.POSITION_UPDATED}:
                position = Position.model_validate(payload)
                positions[position.position_id] = position
            if event_type in {EventType.POSITION_CLOSED, EventType.POSITION_LIQUIDATED}:
                position_id = str(payload["position_id"])
                positions.pop(position_id, None)
        for row in order_rows:
            order = Order.model_validate(json.loads(str(row[0])))
            terminal_time = order.terminal_time_ns
            if terminal_time is not None and terminal_time <= time_ns:
                orders[order.order_id] = order
        fills = tuple(Fill.model_validate(json.loads(str(row[0]))) for row in fill_rows)
        trades = tuple(Trade.model_validate(json.loads(str(row[0]))) for row in trade_rows)
        return (
            tuple(sorted(orders.values(), key=lambda item: item.order_id)),
            tuple(sorted(positions.values(), key=lambda item: item.position_id)),
            fills,
            trades,
        )

    def bootstrap(
        self,
        run_id: str,
        symbol: str | None = None,
        timeframe: Timeframe | None = None,
        cursor_time_ns: int | None = None,
        history_count: int = 500,
    ) -> ReplayBootstrap:
        context = self._context(run_id)
        selected_symbol = symbol or context.manifest.default_symbol
        selected_timeframe = timeframe or context.manifest.default_timeframe
        execution = (
            self.execution_bar_at_or_before_time(run_id, cursor_time_ns)
            if cursor_time_ns is not None
            else self.first_execution_bar(run_id)
        )
        cursor = execution.close_time_ns
        bars = self.history(run_id, selected_symbol, selected_timeframe, cursor, history_count)
        window_start_ns = bars[0].open_time_ns - 1 if bars else context.manifest.start_time_ns - 1
        timeline = self.timeline_for_window(run_id, window_start_ns, cursor, limit=10_000)
        orders, positions, fills, trades = self.state_at(
            run_id,
            cursor,
            history_limit=5_000,
        )
        progress = self.progress(run_id, cursor)
        profile = context.profiles[selected_symbol]
        return ReplayBootstrap(
            run=self.descriptor(run_id),
            symbol=selected_symbol,
            timeframe=selected_timeframe,
            cursor_sequence=execution.sequence,
            cursor_time_ns=cursor,
            progress=progress,
            price_digits=profile.digits,
            price_tick_size=profile.trade_tick_size,
            bars=bars,
            timeline=timeline,
            account=self.account_at(run_id, cursor),
            orders=orders,
            positions=positions,
            fills=fills,
            trades=trades,
            strategy_report=context.strategy_report,
            broker_report=context.strategy_report.broker_report,
        )

    def progress(self, run_id: str, time_ns: int) -> Decimal:
        manifest = self._context(run_id).manifest
        span = manifest.end_time_ns - manifest.start_time_ns
        if span <= 0:
            return Decimal("1")
        bounded = min(max(time_ns, manifest.start_time_ns), manifest.end_time_ns)
        return Decimal(bounded - manifest.start_time_ns) / Decimal(span)

    def analytics(self, run_id: str, end_time_ns: int | None = None) -> AnalyticsReport:
        context = self._context(run_id)
        if end_time_ns is None or end_time_ns >= context.manifest.end_time_ns:
            return context.analytics_report
        bounded_end = max(context.manifest.start_time_ns, end_time_ns)
        equity_curve = self._read_equity_curve(context.database_path, bounded_end)
        trades = self._read_trades(context.database_path, bounded_end)
        effective_end = equity_curve[-1].time_ns if equity_curve else context.manifest.start_time_ns
        return AnalyticsEngine().calculate(
            run_id=run_id,
            currency=context.analytics_report.currency,
            initial_balance=context.analytics_report.performance.initial_balance,
            start_time_ns=context.manifest.start_time_ns,
            end_time_ns=effective_end,
            trades=trades,
            equity_curve=equity_curve,
            config=context.analytics_report.config,
        )

    def analytics_comparison(self, run_ids: tuple[str, ...]) -> AnalyticsComparisonReport:
        selected = run_ids or tuple(sorted(self._contexts))
        rows = []
        for run_id in selected:
            report = self.analytics(run_id)
            descriptor = self.descriptor(run_id)
            rows.append(
                AnalyticsComparisonRow(
                    run_id=run_id,
                    name=descriptor.name,
                    net_pnl=report.performance.net_pnl,
                    total_return_percent=report.performance.total_return_percent,
                    max_drawdown_percent=report.risk.max_drawdown_percent,
                    sharpe_ratio=report.risk.sharpe_ratio,
                    sortino_ratio=report.risk.sortino_ratio,
                    profit_factor=report.performance.profit_factor,
                    win_rate_percent=report.trades.win_rate_percent,
                    total_trades=report.trades.total_trades,
                )
            )
        return AnalyticsComparisonReport(rows=tuple(rows))

    def strategy_report(self, run_id: str) -> StrategyBacktestReport:
        return self._context(run_id).strategy_report

    def broker_report(self, run_id: str) -> BrokerSimulationReport:
        return self._context(run_id).strategy_report.broker_report

    @staticmethod
    def _read_trades(database_path: Path, end_time_ns: int) -> tuple[Trade, ...]:
        with sqlite3.connect(database_path) as connection:
            rows = connection.execute(
                "SELECT payload FROM entities WHERE entity_type = 'trade' "
                "AND event_time_ns <= ? ORDER BY event_time_ns, entity_id",
                (end_time_ns,),
            ).fetchall()
        return tuple(Trade.model_validate(json.loads(str(row[0]))) for row in rows)

    @staticmethod
    def _read_equity_curve(
        database_path: Path,
        end_time_ns: int,
    ) -> tuple[EquityCurvePoint, ...]:
        with sqlite3.connect(database_path) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'equity_curve'"
            ).fetchone()
            if table is not None:
                rows = connection.execute(
                    "SELECT time_ns, balance, equity, floating_pnl, margin, "
                    "drawdown_amount, drawdown_percent FROM equity_curve "
                    "WHERE time_ns <= ? ORDER BY time_ns",
                    (end_time_ns,),
                ).fetchall()
                return tuple(
                    EquityCurvePoint(
                        time_ns=int(row[0]),
                        balance=Decimal(str(row[1])),
                        equity=Decimal(str(row[2])),
                        floating_pnl=Decimal(str(row[3])),
                        margin=Decimal(str(row[4])),
                        drawdown_amount=Decimal(str(row[5])),
                        drawdown_percent=Decimal(str(row[6])),
                    )
                    for row in rows
                )
            rows = connection.execute(
                "SELECT time_ns, payload FROM account_snapshots "
                "WHERE time_ns <= ? ORDER BY time_ns",
                (end_time_ns,),
            ).fetchall()
        result = []
        for time_ns, payload_raw in rows:
            payload = cast(dict[str, Any], json.loads(str(payload_raw)))
            result.append(
                EquityCurvePoint(
                    time_ns=int(time_ns),
                    balance=Decimal(str(payload["balance"])),
                    equity=Decimal(str(payload["equity"])),
                    floating_pnl=Decimal(str(payload["floating_pnl"])),
                    margin=Decimal(str(payload["margin"])),
                    drawdown_amount=Decimal(str(payload["drawdown_amount"])),
                    drawdown_percent=Decimal(str(payload["drawdown_percent"])),
                )
            )
        return tuple(result)

    def close(self) -> None:
        connections = getattr(self._connections, "values", {})
        for _, connection in connections.values():
            connection.close()
        self._connections.values = {}

    def _connection(self, context: _RunContext) -> sqlite3.Connection:
        connections: dict[str, tuple[tuple[int, int], sqlite3.Connection]] = getattr(
            self._connections, "values", {}
        )
        key = str(context.database_path)
        cached = connections.get(key)
        if cached is not None and cached[0] == context.database_signature:
            return cached[1]
        if cached is not None:
            cached[1].close()
        uri = f"{context.database_path.as_uri()}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, check_same_thread=True)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA cache_size = -32768")
        connection.execute("PRAGMA mmap_size = 268435456")
        connections[key] = (context.database_signature, connection)
        self._connections.values = connections
        return connection

    @staticmethod
    def _terminal_order_rows(
        connection: sqlite3.Connection,
        has_terminal_orders: bool,
        time_ns: int,
        limit: int | None,
    ) -> list[tuple[Any, ...]]:
        if has_terminal_orders:
            table = "terminal_orders"
            time_column = "terminal_time_ns"
            id_column = "order_id"
            predicate = "terminal_time_ns <= ?"
            parameters: tuple[Any, ...] = (time_ns,)
        else:
            table = "entities"
            time_column = "event_time_ns"
            id_column = "entity_id"
            predicate = "entity_type = 'order' AND event_time_ns <= ?"
            parameters = (time_ns,)
        if limit is None:
            return connection.execute(
                f"SELECT payload FROM {table} WHERE {predicate} "
                f"ORDER BY {time_column}, {id_column}",
                parameters,
            ).fetchall()
        if limit <= 0:
            return []
        return connection.execute(
            f"SELECT payload FROM ("
            f"SELECT {time_column}, {id_column}, payload FROM {table} "
            f"WHERE {predicate} ORDER BY {time_column} DESC, {id_column} DESC LIMIT ?"
            f") ORDER BY {time_column}, {id_column}",
            (*parameters, limit),
        ).fetchall()

    @staticmethod
    def _history_entity_rows(
        connection: sqlite3.Connection,
        entity_type: str,
        time_ns: int,
        limit: int | None,
    ) -> list[tuple[Any, ...]]:
        if limit is None:
            return connection.execute(
                "SELECT payload FROM entities "
                "WHERE entity_type = ? AND event_time_ns <= ? "
                "ORDER BY event_time_ns, entity_id",
                (entity_type, time_ns),
            ).fetchall()
        if limit <= 0:
            return []
        return connection.execute(
            "SELECT payload FROM ("
            "SELECT event_time_ns, entity_id, payload FROM entities "
            "WHERE entity_type = ? AND event_time_ns <= ? "
            "ORDER BY event_time_ns DESC, entity_id DESC LIMIT ?"
            ") ORDER BY event_time_ns, entity_id",
            (entity_type, time_ns, limit),
        ).fetchall()

    def _context(self, run_id: str) -> _RunContext:
        try:
            return self._contexts[run_id]
        except KeyError as exc:
            raise ReplayRunNotFoundError(run_id) from exc

    @staticmethod
    def _replay_bar(context: _RunContext, row: dict[str, object]) -> ReplayBar:
        profile = context.profiles[str(row["symbol"])]
        tick = profile.trade_tick_size
        return ReplayBar(
            symbol=str(row["symbol"]),
            timeframe=Timeframe(str(row["timeframe"])),
            sequence=int(cast(int, row["sequence"])),
            open_time_ns=int(cast(int, row["open_time_ns"])),
            close_time_ns=int(cast(int, row["close_time_ns"])),
            open=Decimal(int(cast(int, row["open_ticks"]))) * tick,
            high=Decimal(int(cast(int, row["high_ticks"]))) * tick,
            low=Decimal(int(cast(int, row["low_ticks"]))) * tick,
            close=Decimal(int(cast(int, row["close_ticks"]))) * tick,
            tick_volume=int(cast(int, row["tick_volume"])),
            real_volume=Decimal(str(row["real_volume"])),
            source_spread_points=int(cast(int, row["source_spread_points"])),
            is_complete=bool(row["is_complete"]),
        )
