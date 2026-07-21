from contextlib import suppress
from multiprocessing import get_context
from multiprocessing.context import SpawnContext
from multiprocessing.process import BaseProcess
from typing import Protocol, cast

from vex_contracts.strategy_runtime import StrategyOutputBatch
from vex_strategy.exceptions import (
    StrategyExecutionError,
    StrategyProcessError,
    StrategyTimeoutError,
)
from vex_strategy.protocol import (
    WorkerCycleRequest,
    WorkerFailure,
    WorkerRequest,
    WorkerResponse,
    WorkerShutdownRequest,
    WorkerStartRequest,
    WorkerStopRequest,
)
from vex_strategy.worker import strategy_worker_main


class _ConnectionLike(Protocol):
    def send(self, obj: object, /) -> None: ...

    def recv(self) -> object: ...

    def poll(self, timeout: float = 0.0) -> bool: ...

    def close(self) -> None: ...


class IsolatedStrategyProcess:
    def __init__(self, start_request: WorkerStartRequest) -> None:
        self._start_request = start_request
        self._context: SpawnContext = get_context("spawn")
        self._connection: _ConnectionLike | None = None
        self._process: BaseProcess | None = None
        self._started = False
        self._stopped = False

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.is_alive()

    def start(self) -> StrategyOutputBatch:
        if self._started:
            raise StrategyProcessError("strategy process has already started")
        parent, child = self._context.Pipe(duplex=True)
        process = self._context.Process(
            target=strategy_worker_main,
            args=(child, self._start_request),
            name=f"vex-strategy-{self._start_request.run_config.strategy.instance_id}",
        )
        process.start()
        child.close()
        self._connection = cast(_ConnectionLike, parent)
        self._process = process
        self._started = True
        return self._receive(self._start_request.runtime_config.startup_timeout_seconds)

    def cycle(self, request: WorkerCycleRequest) -> StrategyOutputBatch:
        return self._exchange(
            request,
            self._start_request.runtime_config.callback_timeout_seconds,
        )

    def stop(self, request: WorkerStopRequest) -> StrategyOutputBatch:
        if self._stopped:
            raise StrategyProcessError("strategy process has already stopped")
        output = self._exchange(
            request,
            self._start_request.runtime_config.shutdown_timeout_seconds,
        )
        self._stopped = True
        self._join(self._start_request.runtime_config.shutdown_timeout_seconds)
        self._close_connection()
        return output

    def shutdown(self) -> None:
        if not self._started or self._stopped:
            self._close_connection()
            return
        with suppress(StrategyExecutionError):
            self._send(WorkerShutdownRequest())
        self._stopped = True
        self._join(self._start_request.runtime_config.shutdown_timeout_seconds)
        self._close_connection()

    def terminate(self) -> None:
        process = self._process
        if process is not None and process.is_alive():
            process.kill()
            process.join(timeout=1)
        self._stopped = True
        self._close_connection()

    def __enter__(self) -> "IsolatedStrategyProcess":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback_object: object) -> None:
        if exc is None:
            self.shutdown()
        else:
            self.terminate()

    def _exchange(self, request: WorkerRequest, timeout: float) -> StrategyOutputBatch:
        self._send(request)
        return self._receive(timeout)

    def _send(self, request: WorkerRequest) -> None:
        connection = self._require_connection()
        process = self._require_process()
        if not process.is_alive():
            raise StrategyProcessError(
                f"strategy process exited unexpectedly with code {process.exitcode}"
            )
        try:
            connection.send(request)
        except (BrokenPipeError, EOFError, OSError) as exc:
            raise StrategyProcessError("failed to send request to strategy process") from exc

    def _receive(self, timeout: float) -> StrategyOutputBatch:
        connection = self._require_connection()
        process = self._require_process()
        if not connection.poll(timeout):
            self.terminate()
            raise StrategyTimeoutError(f"strategy callback exceeded {timeout:.3f} seconds")
        try:
            response = cast(WorkerResponse, connection.recv())
        except (EOFError, OSError) as exc:
            exit_code = process.exitcode
            self.terminate()
            raise StrategyProcessError(
                f"strategy process closed the channel unexpectedly with code {exit_code}"
            ) from exc
        if isinstance(response, WorkerFailure):
            self.terminate()
            raise StrategyExecutionError(
                f"{response.error_type}: {response.message}\n{response.traceback_text}"
            )
        return response.output

    def _join(self, timeout: float) -> None:
        process = self._process
        if process is None:
            return
        process.join(timeout=timeout)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        if process.exitcode not in {0, None}:
            raise StrategyProcessError(f"strategy process exited with code {process.exitcode}")

    def _close_connection(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _require_connection(self) -> _ConnectionLike:
        if self._connection is None:
            raise StrategyProcessError("strategy process connection is not available")
        return self._connection

    def _require_process(self) -> BaseProcess:
        if self._process is None:
            raise StrategyProcessError("strategy process is not available")
        return self._process
