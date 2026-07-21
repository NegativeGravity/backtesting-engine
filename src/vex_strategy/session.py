from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from vex_broker.exceptions import BrokerError
from vex_broker.models import BrokerResult
from vex_broker.simulator import BrokerSimulator
from vex_contracts.broker import BrokerStateSnapshot
from vex_contracts.chart import ChartCommand
from vex_contracts.enums import PriceBasis
from vex_contracts.events import EventEnvelope
from vex_contracts.json_types import JsonValue
from vex_contracts.market import Bar
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import fingerprint
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import (
    FormingBar,
    StrategyAction,
    StrategyBacktestReport,
    StrategyCallbackStatistics,
    StrategyLogRecord,
    StrategyOutputBatch,
    StrategyRuntimeConfig,
    StrategyWarmupData,
)
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_data_engine.catalog import ParquetBarStore
from vex_data_engine.models import BarCloseBatch
from vex_strategy.exceptions import (
    StrategyActionError,
    StrategyFeedbackLimitError,
    StrategyProcessError,
)
from vex_strategy.executor import StrategyActionExecutor
from vex_strategy.forming import FormingBarCoordinator
from vex_strategy.isolation import IsolatedStrategyProcess
from vex_strategy.observer import NullStrategyRunObserver, StrategyRunObserver
from vex_strategy.output import StrategyOutputRecorder
from vex_strategy.protocol import WorkerCycleRequest, WorkerStartRequest, WorkerStopRequest


@dataclass(slots=True)
class RuntimeCounters:
    processed_close_batches: int = 0
    processed_execution_bars: int = 0
    start_callbacks: int = 0
    bar_callbacks: int = 0
    order_update_callbacks: int = 0
    stop_callbacks: int = 0
    feedback_rounds: int = 0
    action_errors: int = 0

    def add_callbacks(self, callbacks: StrategyCallbackStatistics) -> None:
        self.start_callbacks += callbacks.start
        self.bar_callbacks += callbacks.bar
        self.order_update_callbacks += callbacks.order_update
        self.stop_callbacks += callbacks.stop

    def contract(self) -> StrategyCallbackStatistics:
        return StrategyCallbackStatistics(
            start=self.start_callbacks,
            bar=self.bar_callbacks,
            order_update=self.order_update_callbacks,
            stop=self.stop_callbacks,
        )


@dataclass(frozen=True, slots=True)
class StrategyStepResult:
    event_time_ns: int
    bars: tuple[Bar, ...]
    execution_bars: tuple[Bar, ...]
    broker_events: tuple[EventEnvelope[dict[str, JsonValue]], ...]
    actions: tuple[StrategyAction, ...]
    chart_commands: tuple[ChartCommand, ...]
    logs: tuple[StrategyLogRecord, ...]
    broker_snapshot: BrokerStateSnapshot
    processed_close_batches: int
    processed_execution_bars: int
    completed: bool = False
    report: StrategyBacktestReport | None = None


@dataclass(frozen=True, slots=True)
class _ConsumedOutput:
    broker_events: tuple[EventEnvelope[dict[str, JsonValue]], ...] = ()
    actions: tuple[StrategyAction, ...] = ()
    chart_commands: tuple[ChartCommand, ...] = ()
    logs: tuple[StrategyLogRecord, ...] = ()

    def merge(self, other: "_ConsumedOutput") -> "_ConsumedOutput":
        return _ConsumedOutput(
            broker_events=self.broker_events + other.broker_events,
            actions=self.actions + other.actions,
            chart_commands=self.chart_commands + other.chart_commands,
            logs=self.logs + other.logs,
        )


def datetime_to_ns(value: datetime) -> int:
    normalized = value.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = normalized - epoch
    return (
        delta.days * 86_400_000_000_000 + delta.seconds * 1_000_000_000 + delta.microseconds * 1_000
    )


def bar_from_row(row: dict[str, Any]) -> Bar:
    return Bar(
        symbol=str(row["symbol"]),
        timeframe=Timeframe(str(row["timeframe"])),
        open_time_ns=int(row["open_time_ns"]),
        close_time_ns=int(row["close_time_ns"]),
        open_ticks=int(row["open_ticks"]),
        high_ticks=int(row["high_ticks"]),
        low_ticks=int(row["low_ticks"]),
        close_ticks=int(row["close_ticks"]),
        tick_volume=int(row["tick_volume"]),
        real_volume=Decimal(str(row["real_volume"])),
        source_spread_points=int(row["source_spread_points"]),
        sequence=int(row["sequence"]),
    )


class StrategyBacktestSession:
    def __init__(
        self,
        run_config: BacktestRunConfig,
        descriptor: StrategyDescriptor,
        runtime_config: StrategyRuntimeConfig,
        symbol_profiles: dict[str, SymbolProfile],
        store: ParquetBarStore,
        output_recorder: StrategyOutputRecorder | None = None,
        price_basis: PriceBasis = PriceBasis.BID,
        observer: StrategyRunObserver | None = None,
        strategy_import_paths: tuple[str | Path, ...] = (),
    ) -> None:
        self.run_config = run_config
        self.descriptor = descriptor
        self.runtime_config = runtime_config
        self.symbol_profiles = dict(symbol_profiles)
        self.store = store
        self.recorder = output_recorder or StrategyOutputRecorder(retain_outputs=True)
        self.broker = BrokerSimulator(run_config, symbol_profiles, price_basis)
        self.observer = observer or NullStrategyRunObserver()
        self.strategy_import_paths = tuple(
            str(Path(path).resolve()) for path in strategy_import_paths
        )
        self.counters = RuntimeCounters()
        self._executor = StrategyActionExecutor(self.broker)
        self._start_time_ns = datetime_to_ns(run_config.start_time)
        self._end_time_ns = datetime_to_ns(run_config.end_time)
        self._last_time_ns = self._start_time_ns
        self._forming: FormingBarCoordinator | None = None
        self._process: IsolatedStrategyProcess | None = None
        self._batches: Iterator[BarCloseBatch] | None = None
        self._started = False
        self._finished = False
        self._report: StrategyBacktestReport | None = None
        self._validate()

    @property
    def started(self) -> bool:
        return self._started

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def report(self) -> StrategyBacktestReport | None:
        return self._report

    @property
    def current_time_ns(self) -> int:
        return self._last_time_ns

    def snapshot_report(self) -> StrategyBacktestReport:
        return self._build_report()

    def start(self) -> StrategyStepResult:
        if self._started:
            raise StrategyProcessError("strategy session has already started")
        warmup = self._warmup(self._start_time_ns)
        forming = FormingBarCoordinator(
            self.store,
            self.run_config.subscriptions,
            self.run_config.execution_timeframe,
            self._start_time_ns,
            self._end_time_ns,
        )
        self._warmup_forming(forming, self._start_time_ns)
        warmup = warmup.model_copy(update={"forming_bars": forming.snapshots(self._start_time_ns)})
        process = IsolatedStrategyProcess(
            WorkerStartRequest(
                run_config=self.run_config,
                descriptor=self.descriptor,
                runtime_config=self.runtime_config,
                initial_snapshot=self.broker.state_snapshot,
                warmup=warmup,
                start_time_ns=self._start_time_ns,
                import_paths=self.strategy_import_paths,
            )
        )
        subscriptions = tuple(
            (subscription.symbol, subscription.timeframe)
            for subscription in self.run_config.subscriptions
        )
        self._forming = forming
        self._process = process
        self._batches = self.store.iter_close_batches(
            subscriptions,
            self._start_time_ns,
            self._end_time_ns,
        )
        try:
            start_output = process.start()
            consumed = self._consume_with_feedback(
                process,
                start_output,
                self._start_time_ns,
                warmup.forming_bars,
            )
        except BaseException:
            process.terminate()
            self.recorder.close()
            raise
        self._started = True
        return StrategyStepResult(
            event_time_ns=self._start_time_ns,
            bars=(),
            execution_bars=(),
            broker_events=consumed.broker_events,
            actions=consumed.actions,
            chart_commands=consumed.chart_commands,
            logs=consumed.logs,
            broker_snapshot=self.broker.state_snapshot,
            processed_close_batches=0,
            processed_execution_bars=0,
        )

    def step(self) -> StrategyStepResult:
        if self._finished:
            return self._completed_result()
        if not self._started:
            self.start()
        batches = self._require_batches()
        process = self._require_process()
        forming = self._require_forming()
        try:
            batch = next(batches)
        except StopIteration:
            return self.finish("completed")
        bars = tuple(bar_from_row(row) for row in batch.bars)
        execution_bars = tuple(
            sorted(
                (
                    bar
                    for bar in bars
                    if bar.timeframe is self.run_config.execution_timeframe
                    and bar.open_time_ns >= self._start_time_ns
                ),
                key=lambda bar: (bar.open_time_ns, bar.symbol),
            )
        )
        broker_events: list[EventEnvelope[dict[str, JsonValue]]] = []
        for bar in execution_bars:
            result = self.broker.process_bar(bar)
            broker_events.extend(result.events)
            self.observer.on_execution_bar(bar, result, self.broker.state_snapshot)
            forming.ingest(bar)
            self.counters.processed_execution_bars += 1
        self._last_time_ns = batch.close_time_ns
        forming_bars = forming.snapshots(self._last_time_ns)
        cycle_output = process.cycle(
            WorkerCycleRequest(
                event_time_ns=self._last_time_ns,
                bars=bars,
                forming_bars=forming_bars,
                broker_events=self._serialize_events(tuple(broker_events)),
                broker_snapshot=self.broker.state_snapshot,
            )
        )
        self.counters.processed_close_batches += 1
        consumed = self._consume_with_feedback(
            process,
            cycle_output,
            self._last_time_ns,
            forming_bars,
        )
        return StrategyStepResult(
            event_time_ns=self._last_time_ns,
            bars=bars,
            execution_bars=execution_bars,
            broker_events=tuple(broker_events) + consumed.broker_events,
            actions=consumed.actions,
            chart_commands=consumed.chart_commands,
            logs=consumed.logs,
            broker_snapshot=self.broker.state_snapshot,
            processed_close_batches=self.counters.processed_close_batches,
            processed_execution_bars=self.counters.processed_execution_bars,
        )

    def finish(self, reason: str = "completed") -> StrategyStepResult:
        if self._finished:
            return self._completed_result()
        if not self._started:
            self.start()
        process = self._require_process()
        consumed = _ConsumedOutput()
        try:
            stop_output = process.stop(
                WorkerStopRequest(
                    event_time_ns=self._last_time_ns,
                    reason=reason,
                    broker_snapshot=self.broker.state_snapshot,
                )
            )
            consumed = self._consume_output(stop_output)
            self._report = self._build_report()
            self._finished = True
        except BaseException:
            process.terminate()
            raise
        finally:
            self.recorder.close()
        return StrategyStepResult(
            event_time_ns=self._last_time_ns,
            bars=(),
            execution_bars=(),
            broker_events=consumed.broker_events,
            actions=consumed.actions,
            chart_commands=consumed.chart_commands,
            logs=consumed.logs,
            broker_snapshot=self.broker.state_snapshot,
            processed_close_batches=self.counters.processed_close_batches,
            processed_execution_bars=self.counters.processed_execution_bars,
            completed=True,
            report=self._report,
        )

    def terminate(self) -> None:
        process = self._process
        if process is not None:
            process.terminate()
        self._finished = True
        self.recorder.close()

    def _completed_result(self) -> StrategyStepResult:
        return StrategyStepResult(
            event_time_ns=self._last_time_ns,
            bars=(),
            execution_bars=(),
            broker_events=(),
            actions=(),
            chart_commands=(),
            logs=(),
            broker_snapshot=self.broker.state_snapshot,
            processed_close_batches=self.counters.processed_close_batches,
            processed_execution_bars=self.counters.processed_execution_bars,
            completed=True,
            report=self._report,
        )

    def _consume_with_feedback(
        self,
        process: IsolatedStrategyProcess,
        output: StrategyOutputBatch,
        event_time_ns: int,
        forming_bars: tuple[FormingBar, ...],
    ) -> _ConsumedOutput:
        consumed = self._consume_output(output)
        pending = consumed.broker_events
        feedback_round = 0
        while pending:
            if feedback_round >= self.runtime_config.max_feedback_rounds:
                raise StrategyFeedbackLimitError("strategy feedback round limit exceeded")
            feedback_round += 1
            self.counters.feedback_rounds += 1
            response = process.cycle(
                WorkerCycleRequest(
                    event_time_ns=event_time_ns,
                    bars=(),
                    forming_bars=forming_bars,
                    broker_events=self._serialize_events(pending),
                    broker_snapshot=self.broker.state_snapshot,
                )
            )
            next_consumed = self._consume_output(response)
            consumed = consumed.merge(next_consumed)
            pending = next_consumed.broker_events
        return consumed

    def _consume_output(self, output: StrategyOutputBatch) -> _ConsumedOutput:
        self.counters.add_callbacks(output.callback_statistics)
        for command in output.chart_commands:
            self.recorder.record_chart_command(command)
        for record in output.logs:
            self.recorder.record_log(record)
        events: list[EventEnvelope[dict[str, JsonValue]]] = []
        for action in output.actions:
            self.recorder.record_action(action)
            try:
                result: BrokerResult = self._executor.execute(action)
            except (BrokerError, ValueError) as exc:
                self.counters.action_errors += 1
                if self.runtime_config.fail_on_action_error:
                    raise StrategyActionError(
                        f"strategy action {action.action_id} failed: {exc}"
                    ) from exc
                continue
            events.extend(result.events)
            self.observer.on_broker_result(
                action.requested_time_ns,
                result,
                self.broker.state_snapshot,
            )
        return _ConsumedOutput(
            broker_events=tuple(events),
            actions=output.actions,
            chart_commands=output.chart_commands,
            logs=output.logs,
        )

    def _warmup(self, start_time_ns: int) -> StrategyWarmupData:
        count = self.runtime_config.warmup_bars_per_series
        if count == 0:
            return StrategyWarmupData()
        subscription_order = {
            (subscription.symbol, subscription.timeframe): index
            for index, subscription in enumerate(self.run_config.subscriptions)
        }
        bars: list[Bar] = []
        for subscription in self.run_config.subscriptions:
            frame = self.store.window(
                subscription.symbol,
                subscription.timeframe,
                start_time_ns,
                count,
            )
            bars.extend(bar_from_row(row) for row in frame.iter_rows(named=True))
        bars.sort(
            key=lambda bar: (
                bar.close_time_ns,
                subscription_order[(bar.symbol, bar.timeframe)],
                bar.open_time_ns,
            )
        )
        return StrategyWarmupData(bars=tuple(bars))

    def _warmup_forming(
        self,
        coordinator: FormingBarCoordinator,
        start_time_ns: int,
    ) -> None:
        symbols = sorted({subscription.symbol for subscription in self.run_config.subscriptions})
        for symbol in symbols:
            frame = self.store.load(
                symbol,
                self.run_config.execution_timeframe,
                coordinator.warmup_start_time_ns,
                start_time_ns,
                complete_only=True,
            )
            for row in frame.iter_rows(named=True):
                coordinator.ingest(bar_from_row(row))

    def _build_report(self) -> StrategyBacktestReport:
        broker_report = self.broker.build_report(self.counters.processed_execution_bars)
        output_digest = self.recorder.digest
        deterministic_digest = fingerprint(
            {
                "run": self.run_config,
                "strategy": self.descriptor,
                "runtime": self.runtime_config,
                "callbacks": self.counters.contract(),
                "processed_close_batches": self.counters.processed_close_batches,
                "processed_execution_bars": self.counters.processed_execution_bars,
                "feedback_rounds": self.counters.feedback_rounds,
                "action_errors": self.counters.action_errors,
                "output_digest": output_digest,
                "broker_digest": broker_report.deterministic_digest,
            }
        )
        return StrategyBacktestReport(
            report_id=f"strategy_report_{deterministic_digest[:24]}",
            run_id=self.run_config.run_id,
            strategy_id=self.descriptor.strategy_id,
            strategy_instance_id=self.run_config.strategy.instance_id,
            processed_close_batches=self.counters.processed_close_batches,
            processed_execution_bars=self.counters.processed_execution_bars,
            callbacks=self.counters.contract(),
            action_count=self.recorder.action_count,
            chart_command_count=self.recorder.chart_command_count,
            log_record_count=self.recorder.log_count,
            feedback_round_count=self.counters.feedback_rounds,
            action_error_count=self.counters.action_errors,
            broker_report=broker_report,
            output_digest=output_digest,
            deterministic_digest=deterministic_digest,
        )

    @staticmethod
    def _serialize_events(
        events: tuple[EventEnvelope[dict[str, JsonValue]], ...],
    ) -> tuple[dict[str, JsonValue], ...]:
        return tuple(cast(dict[str, JsonValue], event.model_dump(mode="json")) for event in events)

    def _validate(self) -> None:
        if self.run_config.strategy.strategy_id != self.descriptor.strategy_id:
            raise StrategyProcessError("run strategy_id does not match the descriptor")
        if self.run_config.strategy.version != self.descriptor.version:
            raise StrategyProcessError("run strategy version does not match the descriptor")
        run_subscriptions = tuple(
            (subscription.symbol, subscription.timeframe)
            for subscription in self.run_config.subscriptions
        )
        descriptor_subscriptions = tuple(
            (subscription.symbol, subscription.timeframe)
            for subscription in self.descriptor.subscriptions
        )
        if run_subscriptions != descriptor_subscriptions:
            raise StrategyProcessError("run subscriptions must match descriptor subscriptions")
        available = set(self.store.available())
        missing = [item for item in run_subscriptions if item not in available]
        if missing:
            formatted = ", ".join(f"{symbol}:{timeframe.value}" for symbol, timeframe in missing)
            raise StrategyProcessError(
                f"strategy subscriptions are missing from cache: {formatted}"
            )
        if self.store.report.dataset_id != self.run_config.dataset.dataset_id:
            raise StrategyProcessError("run dataset_id does not match the import report")
        if self.store.report.dataset_version != self.run_config.dataset.version:
            raise StrategyProcessError("run dataset version does not match the import report")

    def _require_process(self) -> IsolatedStrategyProcess:
        if self._process is None:
            raise StrategyProcessError("strategy process is not initialized")
        return self._process

    def _require_forming(self) -> FormingBarCoordinator:
        if self._forming is None:
            raise StrategyProcessError("forming-bar coordinator is not initialized")
        return self._forming

    def _require_batches(self) -> Iterator[BarCloseBatch]:
        if self._batches is None:
            raise StrategyProcessError("bar iterator is not initialized")
        return self._batches
