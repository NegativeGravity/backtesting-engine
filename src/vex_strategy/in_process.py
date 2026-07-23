import traceback

from vex_contracts.strategy_runtime import StrategyOutputBatch
from vex_strategy.base import Strategy
from vex_strategy.context import StrategyContext
from vex_strategy.exceptions import StrategyExecutionError, StrategyProcessError
from vex_strategy.protocol import WorkerCycleRequest, WorkerStartRequest, WorkerStopRequest
from vex_strategy.worker import _cycle, _start, _stop


class InProcessStrategyProcess:
    """Trusted high-throughput strategy runtime without per-candle IPC.

    The callback semantics are identical to the isolated worker. This mode is intended
    only for trusted strategy source because Python process isolation and hard callback
    timeouts are deliberately traded for substantially lower latency.
    """

    def __init__(self, start_request: WorkerStartRequest) -> None:
        self._start_request = start_request
        self._strategy: Strategy | None = None
        self._context: StrategyContext | None = None
        self._subscription_order: dict[tuple[str, str], int] = {}
        self._started = False
        self._stopped = False

    @property
    def is_alive(self) -> bool:
        return self._started and not self._stopped

    def start(self) -> StrategyOutputBatch:
        if self._started:
            raise StrategyProcessError("strategy runtime has already started")
        try:
            strategy, context, output = _start(self._start_request)
        except BaseException as exc:
            raise self._execution_error(exc) from exc
        self._strategy = strategy
        self._context = context
        self._subscription_order = {
            (subscription.symbol, subscription.timeframe.value): index
            for index, subscription in enumerate(self._start_request.run_config.subscriptions)
        }
        self._started = True
        return output

    def cycle(self, request: WorkerCycleRequest) -> StrategyOutputBatch:
        strategy, context = self._require_runtime()
        try:
            return _cycle(strategy, context, request, self._subscription_order)
        except BaseException as exc:
            self._stopped = True
            raise self._execution_error(exc) from exc

    def stop(self, request: WorkerStopRequest) -> StrategyOutputBatch:
        if self._stopped:
            raise StrategyProcessError("strategy runtime has already stopped")
        strategy, context = self._require_runtime()
        try:
            output = _stop(strategy, context, request)
        except BaseException as exc:
            self._stopped = True
            raise self._execution_error(exc) from exc
        self._stopped = True
        return output

    def shutdown(self) -> None:
        self._stopped = True

    def terminate(self) -> None:
        self._stopped = True

    def __enter__(self) -> "InProcessStrategyProcess":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback_object: object) -> None:
        del exc_type, traceback_object
        if exc is None:
            self.shutdown()
        else:
            self.terminate()

    def _require_runtime(self) -> tuple[Strategy, StrategyContext]:
        if not self._started or self._strategy is None or self._context is None:
            raise StrategyProcessError("strategy runtime is not initialized")
        if self._stopped:
            raise StrategyProcessError("strategy runtime is stopped")
        return self._strategy, self._context

    @staticmethod
    def _execution_error(exc: BaseException) -> StrategyExecutionError:
        return StrategyExecutionError(
            f"{type(exc).__name__}: {exc}\n{''.join(traceback.format_exception(exc))}"
        )
