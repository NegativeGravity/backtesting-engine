import asyncio
import re
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import islice
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import JsonValue

from vex_contracts.broker import BrokerSimulationReport
from vex_contracts.market import Bar
from vex_contracts.replay import (
    ReplayBar,
    ReplayBootstrap,
    ReplayCatalog,
    ReplayFrame,
    ReplayMetrics,
    ReplayRunDescriptor,
    ReplayTimelineItem,
)
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import canonical_data, dump_json
from vex_contracts.timeframes import Timeframe
from vex_data_engine.catalog import ParquetBarStore
from vex_orchestrator.catalog import StrategyPackage, StrategyPackageCatalog
from vex_orchestrator.models import (
    LiveRunCatalog,
    LiveRunControlCommand,
    LiveRunCreateRequest,
    LiveRunState,
)
from vex_orchestrator.pacing import DeadlinePacer, ui_publish_interval
from vex_replay.builder import ReplayBundleBuilder
from vex_replay.repository import ReplayRunRepository
from vex_strategy.output import StrategyOutputRecorder
from vex_strategy.session import StrategyBacktestSession, StrategyStepResult, datetime_to_ns


@dataclass(slots=True)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]
    symbol: str
    timeframe: Timeframe
    dropped_messages: int = 0


LIVE_ACCOUNT_TIMELINE_INTERVAL = 250
LIVE_BOOTSTRAP_BAR_LIMIT = 1_000
LIVE_BOOTSTRAP_ENTITY_LIMIT = 5_000
LIVE_BOOTSTRAP_TIMELINE_LIMIT = 5_000
LIVE_MAX_INCREMENTAL_BARS_PER_FRAME = 1_200
LIVE_VISUAL_RESET_WINDOW = 1_000
LIVE_SUBSCRIBER_QUEUE_SIZE = 512
MAX_LIVE_REPLAY_SPEED = Decimal("100000")


class LiveRunNotFoundError(KeyError):
    pass


class LiveBacktestJob:
    def __init__(
        self,
        project_root: Path,
        package: StrategyPackage,
        request: LiveRunCreateRequest,
        replay_ready_callback: Callable[[], None],
    ) -> None:
        self.project_root = project_root
        self.package = package
        self.request = request
        self.run_config = self._build_run_config(package.run_config, request)
        self.run_id = self.run_config.run_id
        self.store = ParquetBarStore.from_report_path(project_root, package.import_report_path)
        self.profiles = {profile.symbol: profile for profile in package.symbol_profiles}
        self.output_root = project_root / "data/live-runs" / self.run_id
        if self.output_root.exists() and any(self.output_root.iterdir()):
            raise ValueError(f"live run working directory already exists: {self.run_id}")
        self.output_root.mkdir(parents=True, exist_ok=True)
        self._strategy_source_root = self.output_root / "strategy-source"
        self._snapshot_strategy_source()
        self._profile_output_paths = tuple(
            self.output_root / "profiles" / f"{profile.symbol}.json"
            for profile in package.symbol_profiles
        )
        self._replay_ready_callback = replay_ready_callback
        self._condition = threading.Condition()
        self._subscribers: list[_Subscriber] = []
        self._thread = threading.Thread(target=self._run_loop, name=f"vex-live-{self.run_id}")
        self._thread.daemon = True
        self._session: StrategyBacktestSession | None = None
        self._status = "created"
        self._playing = not request.start_paused
        self._speed = request.speed_bars_per_second
        self._step_budget = 0
        self._cancel_requested = False
        self._rewind_batches: int | None = None
        self._seek_time_ns: int | None = None
        self._error: str | None = None
        self._replay_ready = False
        self._timeline: deque[ReplayTimelineItem] = deque(maxlen=50_000)
        self._timeline_sequence = 0
        self._created_at = datetime.now(UTC)
        self._updated_at = self._created_at
        self._current_time_ns = datetime_to_ns(self.run_config.start_time)
        self._processed_close_batches = 0
        self._processed_execution_bars = 0
        self._last_report = None
        self._pending_bars: list[Bar] = []
        self._pending_bar_reset = False
        self._recent_bars: dict[tuple[str, Timeframe], deque[Bar]] = {}
        self._pending_timeline: list[ReplayTimelineItem] = []
        self._pending_result: StrategyStepResult | None = None
        self._last_publish_monotonic = 0.0
        self._write_inputs()
        self._replace_session()

    def start(self) -> None:
        self._thread.start()

    def state(self) -> LiveRunState:
        with self._condition:
            return self._state_unlocked()

    def control(self, command: LiveRunControlCommand) -> LiveRunState:
        publish_state = command.action in {"pause", "step_forward", "set_speed"}
        with self._condition:
            if self._status in {"finalizing", "completed", "failed", "cancelled"}:
                raise ValueError(
                    f"live run cannot be controlled while status is {self._status}; "
                    "use the finalized replay after completion"
                )
            if command.action == "play":
                self._playing = True
                if self._status not in {"completed", "failed", "cancelled", "finalizing"}:
                    self._status = "running"
            elif command.action == "pause":
                self._playing = False
                if self._status in {"running", "paused"}:
                    self._status = "paused"
            elif command.action == "step_forward":
                count = int(command.value or 1)
                if count <= 0:
                    raise ValueError("step_forward count must be positive")
                self._playing = False
                self._step_budget += count
                if self._status not in {"completed", "failed", "cancelled", "finalizing"}:
                    self._status = "paused"
            elif command.action == "step_backward":
                self._playing = False
                self._rewind_batches = max(0, self._processed_close_batches - 1)
            elif command.action == "reset":
                self._playing = False
                self._rewind_batches = 0
            elif command.action == "seek_progress":
                if command.value is None:
                    raise ValueError("seek_progress requires a value")
                progress = Decimal(str(command.value))
                if progress < 0 or progress > 1:
                    raise ValueError("seek_progress must be between zero and one")
                start = datetime_to_ns(self.run_config.start_time)
                end = datetime_to_ns(self.run_config.end_time)
                self._playing = False
                self._seek_time_ns = start + int(Decimal(end - start) * progress)
            elif command.action == "set_speed":
                if command.value is None:
                    raise ValueError("set_speed requires a value")
                speed = Decimal(str(command.value))
                if speed <= 0 or speed > MAX_LIVE_REPLAY_SPEED:
                    raise ValueError(
                        f"speed must be greater than zero and at most {MAX_LIVE_REPLAY_SPEED}"
                    )
                self._speed = speed
            elif command.action == "cancel":
                self._cancel_requested = True
                self._playing = False
            self._touch_unlocked()
            self._condition.notify_all()
            state = self._state_unlocked()
        if publish_state:
            self._publish_state()
        return state

    def subscribe(
        self,
        loop: asyncio.AbstractEventLoop,
        symbol: str | None,
        timeframe: Timeframe | None,
    ) -> tuple[_Subscriber, ReplayBootstrap]:
        selected_symbol = symbol or sorted(self.profiles)[0]
        selected_timeframe = timeframe or self.run_config.execution_timeframe
        self._validate_view(selected_symbol, selected_timeframe)
        subscriber = _Subscriber(
            loop,
            asyncio.Queue(maxsize=LIVE_SUBSCRIBER_QUEUE_SIZE),
            selected_symbol,
            selected_timeframe,
        )
        with self._condition:
            self._subscribers.append(subscriber)
            bootstrap = self._bootstrap_unlocked(selected_symbol, selected_timeframe)
        return subscriber, bootstrap

    def unsubscribe(self, subscriber: _Subscriber) -> None:
        with self._condition:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def bootstrap(self, symbol: str | None, timeframe: Timeframe | None) -> ReplayBootstrap:
        selected_symbol = symbol or sorted(self.profiles)[0]
        selected_timeframe = timeframe or self.run_config.execution_timeframe
        self._validate_view(selected_symbol, selected_timeframe)
        with self._condition:
            return self._bootstrap_unlocked(selected_symbol, selected_timeframe)

    async def next_message(self, subscriber: _Subscriber) -> dict[str, Any]:
        return await subscriber.queue.get()

    def update_subscriber_timeframe(
        self,
        subscriber: _Subscriber,
        timeframe: Timeframe,
    ) -> ReplayBootstrap:
        if (subscriber.symbol, timeframe) not in set(self.store.available()):
            raise ValueError(
                f"timeframe is not available for {subscriber.symbol}: {timeframe.value}"
            )
        with self._condition:
            subscriber.timeframe = timeframe
            return self._bootstrap_unlocked(subscriber.symbol, timeframe)

    def _validate_view(self, symbol: str, timeframe: Timeframe) -> None:
        if symbol not in self.profiles:
            raise ValueError(f"symbol is not available: {symbol}")
        if (symbol, timeframe) not in set(self.store.available()):
            raise ValueError(f"timeframe is not available for {symbol}: {timeframe.value}")

    def descriptor(self) -> ReplayRunDescriptor:
        with self._condition:
            return self._descriptor_unlocked()

    def shutdown(self, timeout: float = 10.0) -> None:
        with self._condition:
            if self._status not in {"completed", "failed", "cancelled"}:
                self._cancel_requested = True
                self._playing = False
                self._condition.notify_all()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            session = self._session
            if session is not None and not session.finished:
                session.terminate()
            self._thread.join(timeout=2.0)

    def state_frame(self) -> ReplayFrame:
        with self._condition:
            state = self._state_unlocked()
            return ReplayFrame(
                frame_type="completed" if state.status == "completed" else "state",
                cursor_sequence=state.processed_execution_bars,
                cursor_time_ns=state.current_time_ns,
                progress=state.progress,
                playing=state.playing,
                speed=state.speed_bars_per_second,
                account=self._require_session().broker.state_snapshot.account,
            )

    def _run_loop(self) -> None:
        pacer = DeadlinePacer()
        previous_speed: Decimal | None = None
        try:
            self._status = "starting"
            self._touch()
            start_result = self._require_session().start()
            self._apply_result(start_result, broadcast_bootstrap=True)
            with self._condition:
                self._status = "running" if self._playing else "paused"
                self._touch_unlocked()
            while True:
                with self._condition:
                    while (
                        not self._playing
                        and self._step_budget == 0
                        and not self._cancel_requested
                        and self._rewind_batches is None
                        and self._seek_time_ns is None
                    ):
                        self._condition.wait()
                    if self._cancel_requested:
                        break
                    rewind_batches = self._rewind_batches
                    seek_time_ns = self._seek_time_ns
                    self._rewind_batches = None
                    self._seek_time_ns = None
                    should_step = self._playing or self._step_budget > 0
                    if self._step_budget > 0:
                        self._step_budget -= 1
                if rewind_batches is not None or seek_time_ns is not None:
                    self._rewind(rewind_batches, seek_time_ns)
                    continue
                if not should_step:
                    continue
                if (
                    self.request.max_close_batches is not None
                    and self._processed_close_batches >= self.request.max_close_batches
                ):
                    result = self._require_session().finish("max_close_batches_reached")
                else:
                    result = self._require_session().step()
                self._apply_result(result)
                if result.completed:
                    self._complete()
                    return
                with self._condition:
                    playing = self._playing
                    speed = self._speed
                if playing:
                    if previous_speed != speed:
                        pacer.reset()
                        previous_speed = speed
                    delay = pacer.delay(float(speed))
                    if delay > 0:
                        with self._condition:
                            if self._playing and not self._cancel_requested:
                                self._condition.wait(timeout=delay)
                else:
                    pacer.reset()
                    previous_speed = None
            cancel_result = self._require_session().finish("cancelled")
            self._apply_result(cancel_result)
            with self._condition:
                self._status = "cancelled"
                self._touch_unlocked()
            self._publish_state()
        except BaseException as exc:
            session = self._session
            if session is not None and not session.finished:
                session.terminate()
            with self._condition:
                self._status = "failed"
                self._error = f"{type(exc).__name__}: {exc}"
                self._touch_unlocked()
            self._publish_error(self._error)

    def _rewind(self, target_batches: int | None, target_time_ns: int | None) -> None:
        with self._condition:
            self._status = "rewinding"
            self._touch_unlocked()
        session = self._session
        if session is not None and not session.finished:
            session.terminate()
        self._timeline.clear()
        self._recent_bars.clear()
        self._clear_pending_publish()
        self._timeline_sequence = 0
        self._processed_close_batches = 0
        self._processed_execution_bars = 0
        self._current_time_ns = datetime_to_ns(self.run_config.start_time)
        self._replace_session()
        self._apply_result(self._require_session().start(), broadcast_bootstrap=False)
        while True:
            if target_batches is not None and self._processed_close_batches >= target_batches:
                break
            if target_time_ns is not None and self._current_time_ns >= target_time_ns:
                break
            if (
                self.request.max_close_batches is not None
                and self._processed_close_batches >= self.request.max_close_batches
            ):
                break
            result = self._require_session().step()
            self._apply_result(result, broadcast=False)
            if result.completed:
                break
        with self._condition:
            self._status = "paused"
            self._playing = False
            self._touch_unlocked()
        self._publish_bootstrap()

    def _complete(self) -> None:
        with self._condition:
            self._status = "finalizing"
            self._playing = False
            self._touch_unlocked()
        self._publish_state()
        result = ReplayBundleBuilder(
            project_root=self.project_root,
            run_config_path=self._relative(self.output_root / "run-config.json"),
            strategy_descriptor_path=self._relative(self.output_root / "strategy-descriptor.json"),
            runtime_config_path=self._relative(self.output_root / "runtime-config.json"),
            symbol_profile_paths=tuple(self._relative(path) for path in self._profile_output_paths),
            import_report_path=self._relative(self.package.import_report_path),
            strategy_source_path=self._relative(self._strategy_source_root),
        ).build(self.request.max_close_batches)
        live_report = self._last_report
        if live_report is None:
            raise RuntimeError("live session completed without a strategy report")
        if result.strategy_report.deterministic_digest != live_report.deterministic_digest:
            raise RuntimeError("live and replay-finalization strategy digests do not match")
        self._replay_ready_callback()
        with self._condition:
            self._status = "completed"
            self._replay_ready = True
            self._touch_unlocked()
        self._publish_state()

    def _replace_session(self) -> None:
        recorder = StrategyOutputRecorder(self.output_root / "strategy-output")
        self._session = StrategyBacktestSession(
            self.run_config,
            self.package.descriptor,
            self.package.runtime_config,
            self.profiles,
            self.store,
            recorder,
            strategy_import_paths=(self._strategy_source_root,),
        )

    def _apply_result(
        self,
        result: StrategyStepResult,
        broadcast: bool = True,
        broadcast_bootstrap: bool = False,
    ) -> None:
        with self._condition:
            self._current_time_ns = result.event_time_ns
            self._processed_close_batches = result.processed_close_batches
            self._processed_execution_bars = result.processed_execution_bars
            if result.report is not None:
                self._last_report = result.report
            items = self._timeline_items(result)
            self._timeline.extend(items)
            self._remember_recent_bars(result.bars)
            self._touch_unlocked()
        if broadcast_bootstrap:
            self._publish_bootstrap()
        elif broadcast:
            self._queue_result_for_publish(result, items)

    def _timeline_items(self, result: StrategyStepResult) -> tuple[ReplayTimelineItem, ...]:
        raw: list[tuple[int, int, int, dict[str, JsonValue], str]] = []
        source = 0
        for command in result.chart_commands:
            source += 1
            raw.append(
                (
                    result.event_time_ns,
                    10,
                    source,
                    cast(dict[str, JsonValue], canonical_data(command)),
                    "chart_command",
                )
            )
        for action in result.actions:
            source += 1
            raw.append(
                (
                    action.requested_time_ns,
                    20,
                    source,
                    cast(dict[str, JsonValue], canonical_data(action)),
                    "strategy_action",
                )
            )
        for record in result.logs:
            source += 1
            raw.append(
                (
                    record.time_ns,
                    30,
                    source,
                    cast(dict[str, JsonValue], canonical_data(record)),
                    "strategy_log",
                )
            )
        for event in result.broker_events:
            source += 1
            raw.append(
                (
                    event.event_time_ns,
                    40,
                    source,
                    cast(dict[str, JsonValue], event.model_dump(mode="json")),
                    "broker_event",
                )
            )
        include_account_timeline = (
            result.completed
            or result.processed_close_batches <= 1
            or result.processed_close_batches % LIVE_ACCOUNT_TIMELINE_INTERVAL == 0
        )
        if include_account_timeline:
            source += 1
            account = result.broker_snapshot.account
            raw.append(
                (
                    result.event_time_ns,
                    50,
                    source,
                    cast(dict[str, JsonValue], account.model_dump(mode="json")),
                    "account_snapshot",
                )
            )
        items: list[ReplayTimelineItem] = []
        for time_ns, priority, source_sequence, payload, kind in sorted(raw):
            del priority, source_sequence
            self._timeline_sequence += 1
            items.append(
                ReplayTimelineItem(
                    sequence=self._timeline_sequence,
                    time_ns=time_ns,
                    kind=cast(
                        Literal[
                            "broker_event",
                            "chart_command",
                            "strategy_action",
                            "strategy_log",
                            "account_snapshot",
                        ],
                        kind,
                    ),
                    payload=payload,
                )
            )
        return tuple(items)

    def _queue_result_for_publish(
        self,
        result: StrategyStepResult,
        items: tuple[ReplayTimelineItem, ...],
    ) -> None:
        now = time.monotonic()
        with self._condition:
            if not self._pending_bar_reset:
                self._pending_bars.extend(result.bars)
                if len(self._pending_bars) > LIVE_MAX_INCREMENTAL_BARS_PER_FRAME:
                    self._pending_bars.clear()
                    self._pending_bar_reset = True
            self._pending_timeline.extend(items)
            self._pending_result = result
            force = result.completed or not self._playing
            due = now - self._last_publish_monotonic >= ui_publish_interval(float(self._speed))
        if force or due:
            self._flush_pending_publish(now)

    def _flush_pending_publish(self, now: float | None = None) -> None:
        with self._condition:
            result = self._pending_result
            if result is None:
                return
            bars = self._deduplicate_pending_bars(self._pending_bars)
            bar_reset = self._pending_bar_reset
            items = tuple(self._pending_timeline)
            self._pending_bars.clear()
            self._pending_bar_reset = False
            self._pending_timeline.clear()
            self._pending_result = None
            self._last_publish_monotonic = time.monotonic() if now is None else now
            subscribers = tuple(self._subscribers)
            recent_bars = (
                {key: tuple(value) for key, value in self._recent_bars.items()}
                if bar_reset
                else {}
            )
            state = self._state_unlocked()
        for subscriber in subscribers:
            if bar_reset:
                selected_source = recent_bars.get(
                    (subscriber.symbol, subscriber.timeframe),
                    (),
                )
            else:
                selected_source = tuple(
                    bar
                    for bar in bars
                    if bar.symbol == subscriber.symbol and bar.timeframe is subscriber.timeframe
                )
            selected_bars = tuple(self._replay_bar(bar) for bar in selected_source)
            frame_type = (
                "reset"
                if bar_reset
                else "completed"
                if result.completed
                else "advance"
            )
            frame = ReplayFrame(
                frame_type=frame_type,
                cursor_sequence=result.processed_execution_bars,
                cursor_time_ns=result.event_time_ns,
                progress=state.progress,
                playing=state.playing,
                speed=state.speed_bars_per_second,
                bars=selected_bars,
                timeline=items,
                account=result.broker_snapshot.account,
            )
            self._enqueue(subscriber, {"type": "frame", "data": frame.model_dump(mode="json")})

    def _clear_pending_publish(self) -> None:
        with self._condition:
            self._pending_bars.clear()
            self._pending_bar_reset = False
            self._pending_timeline.clear()
            self._pending_result = None
            self._last_publish_monotonic = time.monotonic()

    def _remember_recent_bars(self, bars: tuple[Bar, ...]) -> None:
        for bar in bars:
            key = (bar.symbol, bar.timeframe)
            recent = self._recent_bars.get(key)
            if recent is None:
                recent = deque(maxlen=LIVE_VISUAL_RESET_WINDOW)
                self._recent_bars[key] = recent
            if recent and recent[-1].sequence == bar.sequence:
                recent[-1] = bar
            elif not recent or recent[-1].sequence < bar.sequence:
                recent.append(bar)

    @staticmethod
    def _deduplicate_pending_bars(bars: list[Bar]) -> tuple[Bar, ...]:
        unique: dict[tuple[str, Timeframe, int], Bar] = {}
        for bar in bars:
            unique[(bar.symbol, bar.timeframe, bar.sequence)] = bar
        return tuple(
            sorted(
                unique.values(),
                key=lambda bar: (bar.close_time_ns, bar.symbol, bar.timeframe.value, bar.sequence),
            )
        )

    def _publish_bootstrap(self) -> None:
        self._clear_pending_publish()
        with self._condition:
            subscribers = tuple(self._subscribers)
            payloads = tuple(
                (subscriber, self._bootstrap_unlocked(subscriber.symbol, subscriber.timeframe))
                for subscriber in subscribers
            )
        for subscriber, bootstrap in payloads:
            self._enqueue(
                subscriber,
                {"type": "bootstrap", "data": bootstrap.model_dump(mode="json")},
            )

    def _publish_state(self) -> None:
        self._flush_pending_publish()
        with self._condition:
            subscribers = tuple(self._subscribers)
            state = self._state_unlocked()
            frame = ReplayFrame(
                frame_type="completed" if state.status == "completed" else "state",
                cursor_sequence=state.processed_execution_bars,
                cursor_time_ns=state.current_time_ns,
                progress=state.progress,
                playing=state.playing,
                speed=state.speed_bars_per_second,
                account=self._require_session().broker.state_snapshot.account,
            )
        message = {"type": "frame", "data": frame.model_dump(mode="json")}
        for subscriber in subscribers:
            self._enqueue(subscriber, message)

    def _publish_error(self, detail: str) -> None:
        with self._condition:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            self._enqueue(subscriber, {"type": "error", "detail": detail})

    @staticmethod
    def _enqueue(subscriber: _Subscriber, message: dict[str, Any]) -> None:
        def put() -> None:
            if subscriber.queue.full():
                dropped = 0
                while True:
                    try:
                        subscriber.queue.get_nowait()
                        dropped += 1
                    except asyncio.QueueEmpty:
                        break
                subscriber.dropped_messages += dropped
                subscriber.queue.put_nowait(
                    {
                        "type": "resync_required",
                        "detail": "subscriber queue overflowed; reconnect for a fresh bootstrap",
                        "dropped_messages": subscriber.dropped_messages,
                    }
                )
                return
            subscriber.queue.put_nowait(message)

        subscriber.loop.call_soon_threadsafe(put)

    def _bootstrap_unlocked(self, symbol: str, timeframe: Timeframe) -> ReplayBootstrap:
        session = self._require_session()
        profile = self.profiles[symbol]
        frame = self.store.window(
            symbol,
            timeframe,
            self._current_time_ns,
            LIVE_BOOTSTRAP_BAR_LIMIT,
        )
        bars = tuple(
            self._replay_bar_from_row(cast(dict[str, object], row), profile.trade_tick_size)
            for row in frame.iter_rows(named=True)
        )
        report = self._last_report or session.snapshot_report()
        broker = session.broker
        return ReplayBootstrap(
            run=self._descriptor_unlocked(),
            symbol=symbol,
            timeframe=timeframe,
            cursor_sequence=self._processed_execution_bars,
            cursor_time_ns=self._current_time_ns,
            progress=self._progress_unlocked(),
            price_digits=profile.digits,
            price_tick_size=profile.trade_tick_size,
            bars=bars,
            timeline=tuple(
                islice(
                    self._timeline,
                    max(0, len(self._timeline) - LIVE_BOOTSTRAP_TIMELINE_LIMIT),
                    None,
                )
            ),
            account=broker.state_snapshot.account,
            orders=broker.orders[-LIVE_BOOTSTRAP_ENTITY_LIMIT:],
            positions=broker.open_positions,
            fills=broker.fills[-LIVE_BOOTSTRAP_ENTITY_LIMIT:],
            trades=broker.trades[-LIVE_BOOTSTRAP_ENTITY_LIMIT:],
            strategy_report=report,
            broker_report=report.broker_report,
        )

    def _descriptor_unlocked(self) -> ReplayRunDescriptor:
        session = self._require_session()
        report = self._last_report or session.snapshot_report()
        available = self.store.available()
        symbols = tuple(sorted({symbol for symbol, _ in available}))
        timeframes = tuple(
            sorted(
                {timeframe for _, timeframe in available},
                key=lambda item: item.seconds or 2**63 - 1,
            )
        )
        return ReplayRunDescriptor(
            run_id=self.run_id,
            name=self.run_config.name,
            strategy_id=self.package.descriptor.strategy_id,
            strategy_instance_id=self.run_config.strategy.instance_id,
            dataset_id=self.run_config.dataset.dataset_id,
            default_symbol=symbols[0],
            default_timeframe=self.run_config.execution_timeframe,
            execution_timeframe=self.run_config.execution_timeframe,
            available_symbols=symbols,
            available_timeframes=timeframes,
            start_time_ns=datetime_to_ns(self.run_config.start_time),
            end_time_ns=datetime_to_ns(self.run_config.end_time),
            metrics=self._metrics(report.broker_report),
        )

    def _state_unlocked(self) -> LiveRunState:
        return LiveRunState(
            run_id=self.run_id,
            strategy_package_id=self.package.manifest.package_id,
            status=cast(
                Literal[
                    "created",
                    "starting",
                    "paused",
                    "running",
                    "rewinding",
                    "finalizing",
                    "completed",
                    "failed",
                    "cancelled",
                ],
                self._status,
            ),
            playing=self._playing and self._status == "running",
            speed_bars_per_second=self._speed,
            processed_close_batches=self._processed_close_batches,
            processed_execution_bars=self._processed_execution_bars,
            current_time_ns=self._current_time_ns,
            progress=self._progress_unlocked(),
            max_close_batches=self.request.max_close_batches,
            error=self._error,
            replay_ready=self._replay_ready,
            created_at=self._created_at,
            updated_at=self._updated_at,
            descriptor=self._descriptor_unlocked(),
        )

    def _progress_unlocked(self) -> Decimal:
        start = datetime_to_ns(self.run_config.start_time)
        end = datetime_to_ns(self.run_config.end_time)
        if end <= start:
            return Decimal("1")
        time_progress = Decimal(min(max(self._current_time_ns, start), end) - start) / Decimal(
            end - start
        )
        if self.request.max_close_batches is None:
            return time_progress
        batch_progress = Decimal(self._processed_close_batches) / Decimal(
            self.request.max_close_batches
        )
        return min(Decimal("1"), max(time_progress, batch_progress))

    def _metrics(self, report: BrokerSimulationReport) -> ReplayMetrics:
        trades = self._require_session().broker.trades
        wins = tuple(trade for trade in trades if trade.net_pnl > 0)
        losses = tuple(trade for trade in trades if trade.net_pnl < 0)
        gross_profit = sum((trade.net_pnl for trade in wins), start=Decimal("0"))
        gross_loss = -sum((trade.net_pnl for trade in losses), start=Decimal("0"))
        total = len(trades)
        r_values = tuple(
            trade.realized_r_multiple for trade in trades if trade.realized_r_multiple is not None
        )
        return ReplayMetrics(
            initial_balance=self.run_config.account.initial_balance,
            final_balance=report.final_account.balance,
            final_equity=report.final_account.equity,
            gross_pnl=report.gross_pnl,
            net_pnl=report.net_pnl,
            commission=report.commission,
            spread_cost=report.spread_cost,
            slippage_cost=report.slippage_cost,
            swap=report.swap,
            total_trades=total,
            winning_trades=len(wins),
            losing_trades=len(losses),
            long_trades=sum(trade.side.value == "long" for trade in trades),
            short_trades=sum(trade.side.value == "short" for trade in trades),
            win_rate=Decimal(len(wins) * 100) / total if total else Decimal("0"),
            profit_factor=gross_profit / gross_loss if gross_loss > 0 else None,
            average_r_multiple=(
                sum(r_values, start=Decimal("0")) / len(r_values) if r_values else None
            ),
            max_drawdown_amount=report.final_account.drawdown_amount,
            max_drawdown_percent=report.final_account.drawdown_percent,
        )

    def _replay_bar(self, bar: Bar) -> ReplayBar:
        profile = self.profiles[bar.symbol]
        tick = profile.trade_tick_size
        return ReplayBar(
            symbol=bar.symbol,
            timeframe=bar.timeframe,
            sequence=bar.sequence,
            open_time_ns=bar.open_time_ns,
            close_time_ns=bar.close_time_ns,
            open=Decimal(bar.open_ticks) * tick,
            high=Decimal(bar.high_ticks) * tick,
            low=Decimal(bar.low_ticks) * tick,
            close=Decimal(bar.close_ticks) * tick,
            tick_volume=bar.tick_volume,
            real_volume=bar.real_volume,
            source_spread_points=bar.source_spread_points,
        )

    @staticmethod
    def _replay_bar_from_row(row: dict[str, object], tick: Decimal) -> ReplayBar:
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

    def _snapshot_strategy_source(self) -> None:
        package_destination = self._strategy_source_root / self.package.root.name
        shutil.copytree(
            self.package.root,
            package_destination,
            dirs_exist_ok=False,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )

    def _write_inputs(self) -> None:
        dump_json(self.run_config, self.output_root / "run-config.json")
        dump_json(self.package.descriptor, self.output_root / "strategy-descriptor.json")
        dump_json(self.package.runtime_config, self.output_root / "runtime-config.json")
        for profile, path in zip(
            self.package.symbol_profiles, self._profile_output_paths, strict=True
        ):
            dump_json(profile, path)

    def _relative(self, path: Path) -> Path:
        return path.resolve().relative_to(self.project_root)

    def _touch(self) -> None:
        with self._condition:
            self._touch_unlocked()

    def _touch_unlocked(self) -> None:
        self._updated_at = datetime.now(UTC)

    def _require_session(self) -> StrategyBacktestSession:
        if self._session is None:
            raise RuntimeError("live strategy session is not initialized")
        return self._session

    @staticmethod
    def _build_run_config(
        base: BacktestRunConfig,
        request: LiveRunCreateRequest,
    ) -> BacktestRunConfig:
        run_id = request.run_id or LiveBacktestJob._generated_run_id(request.strategy_package_id)
        parameters = dict(base.strategy.parameters)
        parameters.update(request.parameters)
        strategy_data = base.strategy.model_dump(mode="python")
        strategy_data.update(
            {
                "instance_id": f"{run_id}.strategy"[:128],
                "parameters": parameters,
            }
        )
        run_data = base.model_dump(mode="python")
        run_data.update(
            {
                "run_id": run_id,
                "name": request.name or f"{base.name} [{run_id}]",
                "strategy": strategy_data,
            }
        )
        if request.start_time is not None:
            run_data["start_time"] = request.start_time
        if request.end_time is not None:
            run_data["end_time"] = request.end_time
        return BacktestRunConfig.model_validate(run_data)

    @staticmethod
    def _generated_run_id(package_id: str) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        normalized = re.sub(r"[^a-z0-9._:-]+", "_", package_id.lower())
        return f"run_{normalized}_{stamp}"


class LiveBacktestManager:
    def __init__(
        self,
        project_root: str | Path,
        catalog: StrategyPackageCatalog,
        replay_repository: ReplayRunRepository,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.catalog = catalog
        self.replay_repository = replay_repository
        self._jobs: dict[str, LiveBacktestJob] = {}
        self._lock = threading.RLock()

    def create(self, request: LiveRunCreateRequest) -> LiveRunState:
        package = self.catalog.get(request.strategy_package_id)
        if request.run_id is not None:
            with self._lock:
                if request.run_id in self._jobs:
                    raise ValueError(f"live run already exists: {request.run_id}")
            try:
                self.replay_repository.descriptor(request.run_id)
            except KeyError:
                pass
            else:
                raise ValueError(f"replay run already exists: {request.run_id}")
        job = LiveBacktestJob(
            self.project_root,
            package,
            request,
            self.replay_repository.refresh,
        )
        with self._lock:
            if job.run_id in self._jobs:
                raise ValueError(f"live run already exists: {job.run_id}")
            try:
                self.replay_repository.descriptor(job.run_id)
            except KeyError:
                pass
            else:
                shutil.rmtree(job.output_root, ignore_errors=True)
                raise ValueError(f"replay run already exists: {job.run_id}")
            self._jobs[job.run_id] = job
        job.start()
        return job.state()

    def get(self, run_id: str) -> LiveBacktestJob:
        with self._lock:
            job = self._jobs.get(run_id)
        if job is None:
            raise LiveRunNotFoundError(run_id)
        return job

    def states(self) -> tuple[LiveRunState, ...]:
        with self._lock:
            jobs = tuple(self._jobs.values())
        return tuple(sorted((job.state() for job in jobs), key=lambda state: state.created_at))

    def catalog_response(self) -> LiveRunCatalog:
        return LiveRunCatalog(strategies=self.catalog.summaries(), runs=self.states())

    def replay_catalog(self) -> ReplayCatalog:
        completed = self.replay_repository.catalog().runs
        live = tuple(state.descriptor for state in self.states() if not state.replay_ready)
        run_map = {run.run_id: run for run in (*completed, *live)}
        return ReplayCatalog(runs=tuple(sorted(run_map.values(), key=lambda run: run.run_id)))

    def control(self, run_id: str, command: LiveRunControlCommand) -> LiveRunState:
        return self.get(run_id).control(command)

    def refresh_strategies(self) -> LiveRunCatalog:
        self.catalog.refresh()
        return self.catalog_response()

    def shutdown(self) -> None:
        with self._lock:
            jobs = tuple(self._jobs.values())
        for job in jobs:
            job.shutdown()
