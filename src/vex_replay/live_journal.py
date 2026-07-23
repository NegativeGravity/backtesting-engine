import hashlib
import json
import shutil
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

from pydantic import JsonValue

from vex_analytics.engine import AnalyticsEngine
from vex_broker.simulator import BrokerSimulator
from vex_contracts.analytics import AnalyticsConfig, EquityCurvePoint
from vex_contracts.replay import (
    ReplayBuildResult,
    ReplayBundleManifest,
    ReplayTimelineItem,
)
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import canonical_data, dump_json
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import StrategyBacktestReport, StrategyRuntimeConfig
from vex_contracts.symbol import SymbolProfile
from vex_data_engine.catalog import ParquetBarStore
from vex_replay.builder import (
    _KIND_PRIORITY,
    ReplayBundleBuilder,
    SqliteReplayObserver,
    _copy_strategy_source,
    _json,
    _metrics,
    _source_digest,
)
from vex_strategy.session import StrategyStepResult, datetime_to_ns


class LiveReplayJournal:
    """Single-pass replay persistence for long-running live backtests.

    The live strategy/broker pass writes the replay database incrementally. Finalization
    only materializes indexes, analytics and manifests; it never reruns the strategy.
    """

    def __init__(
        self,
        project_root: Path,
        run: BacktestRunConfig,
        descriptor: StrategyDescriptor,
        runtime: StrategyRuntimeConfig,
        profiles: tuple[SymbolProfile, ...],
        import_report_path: Path,
        strategy_source_root: Path,
        max_close_batches: int | None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.run = run
        self.descriptor = descriptor
        self.runtime = runtime
        self.profiles = profiles
        self.import_report_path = import_report_path
        self.strategy_source_root = strategy_source_root
        self.max_close_batches = max_close_batches
        self.bundle_root = self.project_root / "data/replay/runs" / run.run_id
        shutil.rmtree(self.bundle_root, ignore_errors=True)
        self.bundle_root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.bundle_root / "replay.sqlite3"
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA temp_store=MEMORY")
        self.connection.execute("PRAGMA cache_size=-65536")
        ReplayBundleBuilder._create_schema(self.connection)
        self.observer = SqliteReplayObserver(
            self.connection,
            snapshot_interval_bars=250,
            equity_sample_interval_bars=10,
            commit_interval_bars=2_048,
        )
        self._chart_sequence = 0
        self._action_sequence = 0
        self._log_sequence = 0
        self._closed = False

    def record_step(self, result: StrategyStepResult) -> None:
        if self._closed:
            return
        for command in result.chart_commands:
            self._chart_sequence += 1
            payload = cast(dict[str, JsonValue], canonical_data(command))
            self._raw(
                self._chart_time(payload, result.event_time_ns),
                "chart_command",
                self._chart_sequence,
                payload,
            )
        for action in result.actions:
            self._action_sequence += 1
            self._raw(
                action.requested_time_ns,
                "strategy_action",
                self._action_sequence,
                cast(dict[str, JsonValue], canonical_data(action)),
            )
        for record in result.logs:
            self._log_sequence += 1
            self._raw(
                record.time_ns,
                "strategy_log",
                self._log_sequence,
                cast(dict[str, JsonValue], canonical_data(record)),
            )

    def timeline_between(
        self,
        start_exclusive_ns: int,
        end_inclusive_ns: int,
        limit: int,
    ) -> tuple[ReplayTimelineItem, ...]:
        if not self.database_path.exists():
            return ()
        with sqlite3.connect(self.database_path, timeout=2.0) as connection:
            rows = connection.execute(
                "SELECT id, time_ns, kind, payload FROM raw_timeline "
                "WHERE time_ns > ? AND time_ns <= ? "
                "ORDER BY time_ns, priority, source_sequence, id LIMIT ?",
                (start_exclusive_ns, end_inclusive_ns, limit),
            ).fetchall()
        return tuple(
            ReplayTimelineItem(
                sequence=int(row_id),
                time_ns=int(time_ns),
                kind=cast(
                    Literal[
                        "broker_event",
                        "chart_command",
                        "strategy_action",
                        "strategy_log",
                        "account_snapshot",
                    ],
                    str(kind),
                ),
                payload=cast(dict[str, JsonValue], json.loads(str(payload))),
            )
            for row_id, time_ns, kind, payload in rows
        )

    def finalize(
        self,
        report: StrategyBacktestReport,
        broker: BrokerSimulator,
    ) -> ReplayBuildResult:
        if self._closed:
            raise RuntimeError("live replay journal is already closed")
        self.observer.flush()
        self._persist_entities(broker)
        ReplayBundleBuilder._materialize_timeline(self.connection)
        metrics = _metrics(
            self.run,
            report,
            broker.trades,
            self.observer.max_drawdown_amount,
            self.observer.max_drawdown_percent,
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("metrics", _json(canonical_data(metrics))),
        )
        equity_curve = self._equity_curve()
        analytics = AnalyticsEngine().calculate(
            run_id=self.run.run_id,
            currency=self.run.account.currency,
            initial_balance=self.run.account.initial_balance,
            start_time_ns=datetime_to_ns(self.run.start_time),
            end_time_ns=report.broker_report.final_account.timestamp_ns,
            trades=broker.trades,
            equity_curve=equity_curve,
            config=AnalyticsConfig(),
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("analytics_report", _json(canonical_data(analytics))),
        )
        self.connection.commit()
        timeline_count = int(self.connection.execute("SELECT COUNT(*) FROM timeline").fetchone()[0])
        snapshot_count = int(
            self.connection.execute("SELECT COUNT(*) FROM account_snapshots").fetchone()[0]
        )
        self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.connection.close()
        self._closed = True

        dump_json(report, self.bundle_root / "strategy-report.json")
        analytics_path = self.bundle_root / "analytics-report.json"
        dump_json(analytics, analytics_path)
        dump_json(self.run, self.bundle_root / "run-config.json")
        dump_json(self.descriptor, self.bundle_root / "strategy-descriptor.json")
        dump_json(self.runtime, self.bundle_root / "strategy-runtime.json")
        dump_json(self.profiles, self.bundle_root / "symbol-profiles.json")

        strategy_module_name = self.descriptor.entrypoint.partition(":")[0].partition(".")[0]
        source = self.strategy_source_root / strategy_module_name
        bundled_source = self.bundle_root / "strategy-source"
        if source.is_dir():
            _copy_strategy_source(source, bundled_source / strategy_module_name)
            source_sha = _source_digest(bundled_source)
            source_path: str | None = bundled_source.relative_to(self.project_root).as_posix()
        else:
            source_sha = None
            source_path = None

        live_output = self.project_root / "data/live-runs" / self.run.run_id / "strategy-output"
        if live_output.is_dir():
            shutil.copytree(live_output, self.bundle_root / "strategy-output", dirs_exist_ok=True)

        store = ParquetBarStore.from_report_path(self.project_root, self.import_report_path)
        available = tuple(store.available())
        symbols = tuple(sorted({symbol for symbol, _ in available}))
        timeframes = tuple(
            sorted(
                {timeframe for _, timeframe in available},
                key=lambda timeframe: timeframe.seconds or 2**63 - 1,
            )
        )
        manifest = ReplayBundleManifest(
            bundle_id=f"bundle_{report.deterministic_digest[:24]}",
            run_id=self.run.run_id,
            name=self.run.name,
            strategy_id=self.descriptor.strategy_id,
            strategy_instance_id=self.run.strategy.instance_id,
            dataset_id=self.run.dataset.dataset_id,
            dataset_version=self.run.dataset.version,
            default_symbol=symbols[0],
            default_timeframe=self.run.execution_timeframe,
            execution_timeframe=self.run.execution_timeframe,
            available_symbols=symbols,
            available_timeframes=timeframes,
            start_time_ns=datetime_to_ns(self.run.start_time),
            end_time_ns=report.broker_report.final_account.timestamp_ns,
            import_report_path=self.import_report_path.relative_to(self.project_root).as_posix(),
            sqlite_path=self.database_path.relative_to(self.project_root).as_posix(),
            symbol_profile_paths=(
                (self.bundle_root / "symbol-profiles.json")
                .relative_to(self.project_root)
                .as_posix(),
            ),
            strategy_report_path=(self.bundle_root / "strategy-report.json")
            .relative_to(self.project_root)
            .as_posix(),
            run_config_path=(self.bundle_root / "run-config.json")
            .relative_to(self.project_root)
            .as_posix(),
            strategy_descriptor_path=(self.bundle_root / "strategy-descriptor.json")
            .relative_to(self.project_root)
            .as_posix(),
            runtime_config_path=(self.bundle_root / "strategy-runtime.json")
            .relative_to(self.project_root)
            .as_posix(),
            analytics_report_path=analytics_path.relative_to(self.project_root).as_posix(),
            strategy_source_path=source_path,
            strategy_source_sha256=source_sha,
            max_close_batches=self.max_close_batches,
            timeline_item_count=timeline_count,
            account_snapshot_count=snapshot_count,
            equity_point_count=len(equity_curve),
        )
        dump_json(manifest, self.bundle_root / "manifest.json")
        database_sha256 = hashlib.sha256(self.database_path.read_bytes()).hexdigest()
        result = ReplayBuildResult(
            manifest=manifest,
            strategy_report=report,
            analytics_report=analytics,
            database_sha256=database_sha256,
            analytics_sha256=hashlib.sha256(analytics_path.read_bytes()).hexdigest(),
        )
        dump_json(result, self.bundle_root / "build-result.json")
        return result

    def reset(self) -> None:
        if not self._closed:
            self.connection.close()
            self._closed = True
        shutil.rmtree(self.bundle_root, ignore_errors=True)

    def close(self) -> None:
        if self._closed:
            return
        self.observer.flush()
        self.connection.close()
        self._closed = True

    def _raw(
        self,
        time_ns: int,
        kind: str,
        source_sequence: int,
        payload: dict[str, JsonValue],
    ) -> None:
        self.connection.execute(
            "INSERT INTO raw_timeline(time_ns, kind, priority, source_sequence, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (time_ns, kind, _KIND_PRIORITY[kind], source_sequence, _json(payload)),
        )

    @staticmethod
    def _chart_time(payload: dict[str, JsonValue], fallback: int) -> int:
        command_type = str(payload.get("command_type", ""))
        if command_type == "append_series_point":
            point = payload.get("point")
            if isinstance(point, dict):
                return int(point.get("time_ns", fallback))
        if command_type == "upsert_drawing":
            drawing = payload.get("drawing")
            if isinstance(drawing, dict):
                for key in ("time_ns", "entry_time_ns"):
                    if key in drawing:
                        return int(drawing[key])
                for key in ("anchor", "start"):
                    point = drawing.get(key)
                    if isinstance(point, dict) and "time_ns" in point:
                        return int(point["time_ns"])
        return fallback

    def _persist_entities(self, broker: BrokerSimulator) -> None:
        def persist(entity_type: str, entity_id: str, time_ns: int, entity: object) -> str:
            payload = _json(canonical_data(entity))
            self.connection.execute(
                "INSERT OR REPLACE INTO entities(entity_type, entity_id, event_time_ns, payload) "
                "VALUES (?, ?, ?, ?)",
                (entity_type, entity_id, time_ns, payload),
            )
            return payload

        for order in broker.orders:
            payload = persist("order", order.order_id, order.request.created_time_ns, order)
            if order.terminal_time_ns is not None:
                self.connection.execute(
                    "INSERT OR REPLACE INTO terminal_orders(order_id, terminal_time_ns, payload) "
                    "VALUES (?, ?, ?)",
                    (order.order_id, order.terminal_time_ns, payload),
                )
        for fill in broker.fills:
            persist("fill", fill.fill_id, fill.time_ns, fill)
        for trade in broker.trades:
            persist("trade", trade.trade_id, trade.exit_time_ns, trade)
        for position in broker.open_positions:
            persist("position", position.position_id, position.opened_time_ns, position)
        self.connection.commit()

    def _equity_curve(self) -> tuple[EquityCurvePoint, ...]:
        rows = self.connection.execute(
            "SELECT time_ns, balance, equity, floating_pnl, margin, "
            "drawdown_amount, drawdown_percent FROM equity_curve ORDER BY time_ns"
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
