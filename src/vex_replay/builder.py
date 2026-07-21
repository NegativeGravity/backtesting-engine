import hashlib
import json
import shutil
import sqlite3
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, JsonValue

from vex_analytics.engine import AnalyticsEngine
from vex_broker.models import BrokerResult
from vex_contracts.analytics import AnalyticsConfig, EquityCurvePoint
from vex_contracts.broker import BrokerStateSnapshot
from vex_contracts.enums import EventType
from vex_contracts.market import Bar
from vex_contracts.replay import ReplayBuildResult, ReplayBundleManifest, ReplayMetrics
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import canonical_data, dump_json, load_json, load_yaml
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import (
    StrategyBacktestReport,
    StrategyRuntimeConfig,
)
from vex_contracts.symbol import SymbolProfile
from vex_data_engine.catalog import ParquetBarStore
from vex_strategy.observer import StrategyRunObserver
from vex_strategy.output import StrategyOutputRecorder
from vex_strategy.runner import StrategyBacktestRunner, datetime_to_ns


class SqliteReplayObserver(StrategyRunObserver):
    def __init__(self, connection: sqlite3.Connection, snapshot_interval_bars: int) -> None:
        self.connection = connection
        self.snapshot_interval_bars = snapshot_interval_bars
        self.bar_count = 0
        self.snapshot_count = 0
        self.max_drawdown_amount = Decimal("0")
        self.max_drawdown_percent = Decimal("0")

    def on_execution_bar(
        self,
        bar: Bar,
        result: BrokerResult,
        snapshot: BrokerStateSnapshot,
    ) -> None:
        self.bar_count += 1
        self.max_drawdown_amount = max(self.max_drawdown_amount, snapshot.account.drawdown_amount)
        self.max_drawdown_percent = max(
            self.max_drawdown_percent, snapshot.account.drawdown_percent
        )
        account = snapshot.account
        self.connection.execute(
            "INSERT OR REPLACE INTO equity_curve("
            "time_ns, balance, equity, floating_pnl, margin, drawdown_amount, drawdown_percent"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot.timestamp_ns,
                str(account.balance),
                str(account.equity),
                str(account.floating_pnl),
                str(account.margin),
                str(account.drawdown_amount),
                str(account.drawdown_percent),
            ),
        )
        self._record_result(result, snapshot, force_snapshot=False)

    def on_broker_result(
        self,
        event_time_ns: int,
        result: BrokerResult,
        snapshot: BrokerStateSnapshot,
    ) -> None:
        del event_time_ns
        self._record_result(result, snapshot, force_snapshot=bool(result.events))

    def _record_result(
        self,
        result: BrokerResult,
        snapshot: BrokerStateSnapshot,
        force_snapshot: bool,
    ) -> None:
        for event in result.events:
            payload = cast(dict[str, JsonValue], event.model_dump(mode="json"))
            self._raw(event.event_time_ns, "broker_event", event.sequence, payload)
            self.connection.execute(
                "INSERT OR REPLACE INTO broker_events("
                "event_id, sequence, time_ns, event_type, payload"
                ") VALUES (?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.sequence,
                    event.event_time_ns,
                    event.event_type.value,
                    _json(payload),
                ),
            )
        should_snapshot = (
            force_snapshot
            or self.bar_count == 1
            or self.bar_count % self.snapshot_interval_bars == 0
            or bool(result.events)
            or bool(result.trades)
        )
        if should_snapshot:
            account_payload = snapshot.account.model_dump(mode="json")
            self.connection.execute(
                "INSERT OR REPLACE INTO account_snapshots(time_ns, event_sequence, payload) "
                "VALUES (?, ?, ?)",
                (snapshot.timestamp_ns, snapshot.event_sequence, _json(account_payload)),
            )
            state_changed = any(
                event.event_type is not EventType.ACCOUNT_UPDATED for event in result.events
            )
            should_state_snapshot = (
                self.bar_count == 1
                or self.bar_count % self.snapshot_interval_bars == 0
                or bool(result.trades)
                or state_changed
            )
            if should_state_snapshot:
                active_orders = tuple(
                    order for order in snapshot.orders if order.terminal_time_ns is None
                )
                self.connection.execute(
                    "INSERT OR REPLACE INTO broker_state_snapshots("
                    "time_ns, event_sequence, orders, positions"
                    ") VALUES (?, ?, ?, ?)",
                    (
                        snapshot.timestamp_ns,
                        snapshot.event_sequence,
                        _json(canonical_data(active_orders)),
                        _json(canonical_data(snapshot.positions)),
                    ),
                )
            self._raw(
                snapshot.timestamp_ns,
                "account_snapshot",
                snapshot.event_sequence,
                cast(dict[str, JsonValue], account_payload),
            )
            self.snapshot_count += 1
        self.connection.commit()

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


_KIND_PRIORITY = {
    "chart_command": 10,
    "strategy_action": 20,
    "strategy_log": 30,
    "broker_event": 40,
    "account_snapshot": 50,
}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        candidate
        for candidate in root.rglob("*")
        if candidate.is_file()
        and "__pycache__" not in candidate.parts
        and path_suffix_allowed(candidate)
    ):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def path_suffix_allowed(path: Path) -> bool:
    return path.suffix.lower() not in {".pyc", ".pyo"}


def _copy_strategy_source(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        return
    shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


def _load_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    value: Any = load_json(path) if path.suffix.lower() == ".json" else load_yaml(path)
    return model.model_validate(value)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return ()
    with path.open("r", encoding="utf-8") as stream:
        return tuple(json.loads(line) for line in stream if line.strip())


def _metrics(
    run: BacktestRunConfig,
    report: StrategyBacktestReport,
    trades: tuple[Any, ...],
    max_drawdown_amount: Decimal,
    max_drawdown_percent: Decimal,
) -> ReplayMetrics:
    wins = tuple(trade for trade in trades if trade.net_pnl > 0)
    losses = tuple(trade for trade in trades if trade.net_pnl < 0)
    gross_profit = sum((trade.net_pnl for trade in wins), start=Decimal("0"))
    gross_loss = -sum((trade.net_pnl for trade in losses), start=Decimal("0"))
    total = len(trades)
    r_values = tuple(
        trade.realized_r_multiple for trade in trades if trade.realized_r_multiple is not None
    )
    average_r = sum(r_values, start=Decimal("0")) / len(r_values) if r_values else None
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    win_rate = Decimal(len(wins) * 100) / total if total else Decimal("0")
    broker = report.broker_report
    return ReplayMetrics(
        initial_balance=run.account.initial_balance,
        final_balance=broker.final_account.balance,
        final_equity=broker.final_account.equity,
        gross_pnl=broker.gross_pnl,
        net_pnl=broker.net_pnl,
        commission=broker.commission,
        spread_cost=broker.spread_cost,
        slippage_cost=broker.slippage_cost,
        swap=broker.swap,
        total_trades=total,
        winning_trades=len(wins),
        losing_trades=len(losses),
        long_trades=sum(trade.side.value == "long" for trade in trades),
        short_trades=sum(trade.side.value == "short" for trade in trades),
        win_rate=win_rate,
        profit_factor=profit_factor,
        average_r_multiple=average_r,
        max_drawdown_amount=max_drawdown_amount,
        max_drawdown_percent=max_drawdown_percent,
    )


class ReplayBundleBuilder:
    def __init__(
        self,
        project_root: str | Path,
        run_config_path: str | Path,
        strategy_descriptor_path: str | Path,
        runtime_config_path: str | Path,
        symbol_profile_paths: Iterable[str | Path],
        import_report_path: str | Path,
        output_root: str | Path = "data/replay/runs",
        snapshot_interval_bars: int = 25,
        strategy_source_path: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.run_config_path = Path(run_config_path)
        self.strategy_descriptor_path = Path(strategy_descriptor_path)
        self.runtime_config_path = Path(runtime_config_path)
        self.symbol_profile_paths = tuple(Path(path) for path in symbol_profile_paths)
        self.import_report_path = Path(import_report_path)
        self.output_root = Path(output_root)
        self.snapshot_interval_bars = snapshot_interval_bars
        self.strategy_source_path = (
            None if strategy_source_path is None else Path(strategy_source_path)
        )

    def build(self, max_close_batches: int | None = None) -> ReplayBuildResult:
        run = _load_model(self.project_root / self.run_config_path, BacktestRunConfig)
        descriptor = _load_model(
            self.project_root / self.strategy_descriptor_path,
            StrategyDescriptor,
        )
        runtime = _load_model(self.project_root / self.runtime_config_path, StrategyRuntimeConfig)
        profiles = tuple(
            _load_model(self.project_root / path, SymbolProfile)
            for path in self.symbol_profile_paths
        )
        bundle_root = self.project_root / self.output_root / run.run_id
        bundle_root.mkdir(parents=True, exist_ok=True)
        database_path = bundle_root / "replay.sqlite3"
        if database_path.exists():
            database_path.unlink()
        connection = sqlite3.connect(database_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        self._create_schema(connection)
        observer = SqliteReplayObserver(connection, self.snapshot_interval_bars)
        raw_output = bundle_root / "strategy-output"
        recorder = StrategyOutputRecorder(raw_output)
        store = ParquetBarStore.from_report_path(
            self.project_root,
            self.project_root / self.import_report_path,
        )
        source_root = (
            None
            if self.strategy_source_path is None
            else (self.project_root / self.strategy_source_path).resolve()
        )
        strategy_package_source: Path | None = None
        strategy_import_root: Path | None = None
        strategy_module_name = descriptor.entrypoint.partition(":")[0].partition(".")[0]
        if source_root is not None:
            if not source_root.is_dir():
                raise FileNotFoundError(f"strategy source directory not found: {source_root}")
            if source_root.name == strategy_module_name:
                strategy_package_source = source_root
                strategy_import_root = source_root.parent
            else:
                strategy_package_source = source_root / strategy_module_name
                strategy_import_root = source_root
            if not strategy_package_source.is_dir():
                raise FileNotFoundError(
                    "strategy entrypoint package is missing from the source snapshot: "
                    f"{strategy_package_source}"
                )
        runner = StrategyBacktestRunner(
            run,
            descriptor,
            runtime,
            {profile.symbol: profile for profile in profiles},
            store,
            recorder,
            observer=observer,
            strategy_import_paths=(() if strategy_import_root is None else (strategy_import_root,)),
        )
        report = runner.run(max_close_batches)
        start_time_ns = datetime_to_ns(run.start_time)
        self._ingest_strategy_outputs(connection, raw_output, start_time_ns)
        self._persist_entities(connection, runner)
        self._materialize_timeline(connection)
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            (
                "metrics",
                _json(
                    canonical_data(
                        _metrics(
                            run,
                            report,
                            runner.broker.trades,
                            observer.max_drawdown_amount,
                            observer.max_drawdown_percent,
                        )
                    )
                ),
            ),
        )
        connection.commit()
        timeline_count = int(connection.execute("SELECT COUNT(*) FROM timeline").fetchone()[0])
        snapshot_count = int(
            connection.execute("SELECT COUNT(*) FROM account_snapshots").fetchone()[0]
        )
        equity_rows = connection.execute(
            "SELECT time_ns, balance, equity, floating_pnl, margin, "
            "drawdown_amount, drawdown_percent FROM equity_curve ORDER BY time_ns"
        ).fetchall()
        equity_curve = tuple(
            EquityCurvePoint(
                time_ns=int(row[0]),
                balance=Decimal(str(row[1])),
                equity=Decimal(str(row[2])),
                floating_pnl=Decimal(str(row[3])),
                margin=Decimal(str(row[4])),
                drawdown_amount=Decimal(str(row[5])),
                drawdown_percent=Decimal(str(row[6])),
            )
            for row in equity_rows
        )
        analytics_report = AnalyticsEngine().calculate(
            run_id=run.run_id,
            currency=run.account.currency,
            initial_balance=run.account.initial_balance,
            start_time_ns=start_time_ns,
            end_time_ns=report.broker_report.final_account.timestamp_ns,
            trades=runner.broker.trades,
            equity_curve=equity_curve,
            config=AnalyticsConfig(),
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("analytics_report", _json(canonical_data(analytics_report))),
        )
        connection.commit()
        connection.close()
        dump_json(report, bundle_root / "strategy-report.json")
        analytics_path = bundle_root / "analytics-report.json"
        dump_json(analytics_report, analytics_path)
        dump_json(run, bundle_root / "run-config.json")
        dump_json(descriptor, bundle_root / "strategy-descriptor.json")
        dump_json(runtime, bundle_root / "strategy-runtime.json")
        dump_json(profiles, bundle_root / "symbol-profiles.json")
        bundled_source_path: Path | None = None
        bundled_source_sha256: str | None = None
        if strategy_package_source is not None:
            bundled_source_path = bundle_root / "strategy-source"
            shutil.rmtree(bundled_source_path, ignore_errors=True)
            _copy_strategy_source(
                strategy_package_source,
                bundled_source_path / strategy_module_name,
            )
            bundled_source_sha256 = _source_digest(bundled_source_path)
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
            run_id=run.run_id,
            name=run.name,
            strategy_id=descriptor.strategy_id,
            strategy_instance_id=run.strategy.instance_id,
            dataset_id=run.dataset.dataset_id,
            dataset_version=run.dataset.version,
            default_symbol=symbols[0],
            default_timeframe=run.execution_timeframe,
            execution_timeframe=run.execution_timeframe,
            available_symbols=symbols,
            available_timeframes=timeframes,
            start_time_ns=start_time_ns,
            end_time_ns=report.broker_report.final_account.timestamp_ns,
            import_report_path=self.import_report_path.as_posix(),
            sqlite_path=(bundle_root / "replay.sqlite3").relative_to(self.project_root).as_posix(),
            symbol_profile_paths=(
                (bundle_root / "symbol-profiles.json").relative_to(self.project_root).as_posix(),
            ),
            strategy_report_path=(
                (bundle_root / "strategy-report.json").relative_to(self.project_root).as_posix()
            ),
            run_config_path=(bundle_root / "run-config.json")
            .relative_to(self.project_root)
            .as_posix(),
            strategy_descriptor_path=(
                (bundle_root / "strategy-descriptor.json").relative_to(self.project_root).as_posix()
            ),
            runtime_config_path=(
                (bundle_root / "strategy-runtime.json").relative_to(self.project_root).as_posix()
            ),
            analytics_report_path=analytics_path.relative_to(self.project_root).as_posix(),
            strategy_source_path=(
                None
                if bundled_source_path is None
                else bundled_source_path.relative_to(self.project_root).as_posix()
            ),
            strategy_source_sha256=bundled_source_sha256,
            max_close_batches=max_close_batches,
            timeline_item_count=timeline_count,
            account_snapshot_count=snapshot_count,
            equity_point_count=len(equity_curve),
        )
        dump_json(manifest, bundle_root / "manifest.json")
        database_sha256 = hashlib.sha256(database_path.read_bytes()).hexdigest()
        result = ReplayBuildResult(
            manifest=manifest,
            strategy_report=report,
            analytics_report=analytics_report,
            database_sha256=database_sha256,
            analytics_sha256=hashlib.sha256(analytics_path.read_bytes()).hexdigest(),
        )
        dump_json(result, bundle_root / "build-result.json")
        return result

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE raw_timeline(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time_ns INTEGER NOT NULL,
                kind TEXT NOT NULL,
                priority INTEGER NOT NULL,
                source_sequence INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE timeline(
                sequence INTEGER PRIMARY KEY,
                time_ns INTEGER NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX timeline_time_idx ON timeline(time_ns, sequence);
            CREATE TABLE account_snapshots(
                time_ns INTEGER PRIMARY KEY,
                event_sequence INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE broker_state_snapshots(
                time_ns INTEGER NOT NULL,
                event_sequence INTEGER NOT NULL,
                orders TEXT NOT NULL,
                positions TEXT NOT NULL,
                PRIMARY KEY(time_ns, event_sequence)
            );
            CREATE INDEX broker_state_snapshots_time_idx
                ON broker_state_snapshots(time_ns, event_sequence);
            CREATE TABLE equity_curve(
                time_ns INTEGER PRIMARY KEY,
                balance TEXT NOT NULL,
                equity TEXT NOT NULL,
                floating_pnl TEXT NOT NULL,
                margin TEXT NOT NULL,
                drawdown_amount TEXT NOT NULL,
                drawdown_percent TEXT NOT NULL
            );
            CREATE TABLE broker_events(
                event_id TEXT PRIMARY KEY,
                sequence INTEGER NOT NULL,
                time_ns INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX broker_events_time_idx ON broker_events(time_ns, sequence);
            CREATE TABLE entities(
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                event_time_ns INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(entity_type, entity_id)
            );
            CREATE INDEX entities_time_idx ON entities(entity_type, event_time_ns);
            CREATE TABLE terminal_orders(
                order_id TEXT PRIMARY KEY,
                terminal_time_ns INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX terminal_orders_time_idx
                ON terminal_orders(terminal_time_ns, order_id);
            CREATE TABLE metadata(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _ingest_strategy_outputs(
        connection: sqlite3.Connection,
        output_root: Path,
        start_time_ns: int,
    ) -> None:
        previous_command_time = start_time_ns
        for index, payload in enumerate(_read_jsonl(output_root / "chart-commands.jsonl"), start=1):
            command_type = payload["command_type"]
            time_ns = start_time_ns
            if command_type == "append_series_point":
                time_ns = int(payload["point"]["time_ns"])
            elif command_type == "upsert_drawing":
                drawing = payload["drawing"]
                for key in ("time_ns", "entry_time_ns"):
                    if key in drawing:
                        time_ns = int(drawing[key])
                        break
                else:
                    if "anchor" in drawing:
                        time_ns = int(drawing["anchor"]["time_ns"])
                    elif "start" in drawing:
                        time_ns = int(drawing["start"]["time_ns"])
                    else:
                        time_ns = previous_command_time
            elif command_type in {"delete_drawing", "clear_layer"}:
                time_ns = previous_command_time
            previous_command_time = max(previous_command_time, time_ns)
            connection.execute(
                "INSERT INTO raw_timeline(time_ns, kind, priority, source_sequence, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (time_ns, "chart_command", _KIND_PRIORITY["chart_command"], index, _json(payload)),
            )
        for index, payload in enumerate(
            _read_jsonl(output_root / "strategy-actions.jsonl"), start=1
        ):
            time_ns = int(payload["requested_time_ns"])
            connection.execute(
                "INSERT INTO raw_timeline(time_ns, kind, priority, source_sequence, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    time_ns,
                    "strategy_action",
                    _KIND_PRIORITY["strategy_action"],
                    index,
                    _json(payload),
                ),
            )
        for index, payload in enumerate(_read_jsonl(output_root / "strategy-logs.jsonl"), start=1):
            time_ns = int(payload["time_ns"])
            connection.execute(
                "INSERT INTO raw_timeline(time_ns, kind, priority, source_sequence, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (time_ns, "strategy_log", _KIND_PRIORITY["strategy_log"], index, _json(payload)),
            )
        connection.commit()

    @staticmethod
    def _persist_entities(connection: sqlite3.Connection, runner: StrategyBacktestRunner) -> None:
        def persist(entity_type: str, entity_id: str, time_ns: int, entity: object) -> str:
            payload = _json(canonical_data(entity))
            connection.execute(
                "INSERT OR REPLACE INTO entities(entity_type, entity_id, event_time_ns, payload) "
                "VALUES (?, ?, ?, ?)",
                (entity_type, entity_id, time_ns, payload),
            )
            return payload

        for order in runner.broker.orders:
            payload = persist(
                "order",
                order.order_id,
                order.request.created_time_ns,
                order,
            )
            if order.terminal_time_ns is not None:
                connection.execute(
                    "INSERT OR REPLACE INTO terminal_orders("
                    "order_id, terminal_time_ns, payload"
                    ") VALUES (?, ?, ?)",
                    (order.order_id, order.terminal_time_ns, payload),
                )
        for fill in runner.broker.fills:
            persist("fill", fill.fill_id, fill.time_ns, fill)
        for trade in runner.broker.trades:
            persist("trade", trade.trade_id, trade.exit_time_ns, trade)
        for position in runner.broker.open_positions:
            persist("position", position.position_id, position.opened_time_ns, position)
        connection.commit()

    @staticmethod
    def _materialize_timeline(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT time_ns, kind, payload FROM raw_timeline "
            "ORDER BY time_ns, priority, source_sequence, id"
        ).fetchall()
        connection.executemany(
            "INSERT INTO timeline(sequence, time_ns, kind, payload) VALUES (?, ?, ?, ?)",
            (
                (sequence, int(time_ns), str(kind), str(payload))
                for sequence, (time_ns, kind, payload) in enumerate(rows, start=1)
            ),
        )
        connection.execute("DROP TABLE raw_timeline")
        connection.commit()
