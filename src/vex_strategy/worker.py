import importlib
import sys
import traceback
from collections.abc import Callable
from multiprocessing.connection import Connection

from vex_contracts.enums import EventType
from vex_contracts.events import EventEnvelope
from vex_contracts.json_types import JsonValue
from vex_contracts.strategy_runtime import StrategyCallbackStatistics, StrategyOutputBatch
from vex_strategy.base import Strategy
from vex_strategy.context import StrategyContext
from vex_strategy.loader import load_strategy_class
from vex_strategy.protocol import (
    WorkerCycleRequest,
    WorkerFailure,
    WorkerRequest,
    WorkerStartRequest,
    WorkerStopRequest,
    WorkerSuccess,
)


def _combine(
    outputs: list[StrategyOutputBatch],
    statistics: StrategyCallbackStatistics,
) -> StrategyOutputBatch:
    return StrategyOutputBatch(
        actions=tuple(action for output in outputs for action in output.actions),
        chart_commands=tuple(command for output in outputs for command in output.chart_commands),
        logs=tuple(record for output in outputs for record in output.logs),
        callback_statistics=statistics,
    )


def _invoke(
    context: StrategyContext,
    callback: Callable[[], None],
    orders_allowed: bool = True,
) -> StrategyOutputBatch:
    context.begin_callback(orders_allowed)
    callback()
    return context.drain()


def _start(start: WorkerStartRequest) -> tuple[Strategy, StrategyContext, StrategyOutputBatch]:
    for import_path in reversed(start.import_paths):
        if import_path not in sys.path:
            sys.path.insert(0, import_path)
    importlib.invalidate_caches()
    strategy_class = load_strategy_class(start.descriptor.entrypoint)
    strategy = strategy_class(start.run_config.strategy.parameters)
    context = StrategyContext(
        start.run_config,
        start.descriptor,
        start.runtime_config,
        strategy.parameters,
        start.initial_snapshot,
    )
    context.apply_warmup(start.warmup.bars, start.warmup.forming_bars)
    context.update_cycle(
        start.start_time_ns,
        (),
        start.warmup.forming_bars,
        start.initial_snapshot,
        (),
    )
    output = _invoke(context, lambda: strategy.on_start(context))
    return (
        strategy,
        context,
        output.model_copy(update={"callback_statistics": StrategyCallbackStatistics(start=1)}),
    )


def _cycle(
    strategy: Strategy,
    context: StrategyContext,
    request: WorkerCycleRequest,
    subscription_order: dict[tuple[str, str], int],
) -> StrategyOutputBatch:
    broker_events = tuple(
        EventEnvelope[dict[str, JsonValue]].model_validate(event) for event in request.broker_events
    )
    context.update_cycle(
        request.event_time_ns,
        request.bars,
        request.forming_bars,
        request.broker_snapshot,
        broker_events,
    )
    outputs: list[StrategyOutputBatch] = []
    order_update_count = 0
    for event in broker_events:
        if event.event_type not in {
            EventType.ORDER_CREATED,
            EventType.ORDER_ACCEPTED,
            EventType.ORDER_ACTIVATED,
            EventType.ORDER_PARTIALLY_FILLED,
            EventType.ORDER_FILLED,
            EventType.ORDER_CANCELLED,
            EventType.ORDER_MODIFIED,
            EventType.ORDER_REJECTED,
            EventType.ORDER_EXPIRED,
            EventType.POSITION_OPENED,
            EventType.POSITION_UPDATED,
            EventType.POSITION_CLOSED,
            EventType.POSITION_LIQUIDATED,
        }:
            continue
        outputs.append(
            _invoke(context, lambda event=event: strategy.on_order_update(context, event))
        )
        order_update_count += 1
    bars = sorted(
        request.bars,
        key=lambda bar: (
            subscription_order[(bar.symbol, bar.timeframe.value)],
            bar.open_time_ns,
        ),
    )
    for bar in bars:
        outputs.append(_invoke(context, lambda bar=bar: strategy.on_bar(context, bar)))
    return _combine(
        outputs,
        StrategyCallbackStatistics(
            bar=len(bars),
            order_update=order_update_count,
        ),
    )


def _stop(
    strategy: Strategy,
    context: StrategyContext,
    request: WorkerStopRequest,
) -> StrategyOutputBatch:
    context.update_cycle(
        request.event_time_ns,
        (),
        (),
        request.broker_snapshot,
        (),
    )
    output = _invoke(
        context,
        lambda: strategy.on_stop(context, request.reason),
        orders_allowed=False,
    )
    return output.model_copy(update={"callback_statistics": StrategyCallbackStatistics(stop=1)})


def strategy_worker_main(connection: Connection, start: WorkerStartRequest) -> None:
    try:
        strategy, context, start_output = _start(start)
        connection.send(WorkerSuccess(start_output))
        subscription_order = {
            (subscription.symbol, subscription.timeframe.value): index
            for index, subscription in enumerate(start.run_config.subscriptions)
        }
        while True:
            request: WorkerRequest = connection.recv()
            if isinstance(request, WorkerCycleRequest):
                connection.send(
                    WorkerSuccess(_cycle(strategy, context, request, subscription_order))
                )
                continue
            if isinstance(request, WorkerStopRequest):
                connection.send(WorkerSuccess(_stop(strategy, context, request)))
                break
            break
    except BaseException as exc:
        connection.send(
            WorkerFailure(
                error_type=type(exc).__name__,
                message=str(exc),
                traceback_text=traceback.format_exc(),
            )
        )
    finally:
        connection.close()
