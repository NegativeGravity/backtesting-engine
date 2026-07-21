from dataclasses import dataclass

from vex_contracts.broker import BrokerStateSnapshot
from vex_contracts.json_types import JsonValue
from vex_contracts.market import Bar
from vex_contracts.run import BacktestRunConfig
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import (
    FormingBar,
    StrategyOutputBatch,
    StrategyRuntimeConfig,
    StrategyWarmupData,
)


@dataclass(frozen=True, slots=True)
class WorkerStartRequest:
    run_config: BacktestRunConfig
    descriptor: StrategyDescriptor
    runtime_config: StrategyRuntimeConfig
    initial_snapshot: BrokerStateSnapshot
    warmup: StrategyWarmupData
    start_time_ns: int
    import_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkerCycleRequest:
    event_time_ns: int
    bars: tuple[Bar, ...]
    forming_bars: tuple[FormingBar, ...]
    broker_events: tuple[dict[str, JsonValue], ...]
    broker_snapshot: BrokerStateSnapshot


@dataclass(frozen=True, slots=True)
class WorkerStopRequest:
    event_time_ns: int
    reason: str
    broker_snapshot: BrokerStateSnapshot


@dataclass(frozen=True, slots=True)
class WorkerShutdownRequest:
    pass


type WorkerRequest = WorkerCycleRequest | WorkerStopRequest | WorkerShutdownRequest


@dataclass(frozen=True, slots=True)
class WorkerSuccess:
    output: StrategyOutputBatch


@dataclass(frozen=True, slots=True)
class WorkerFailure:
    error_type: str
    message: str
    traceback_text: str


type WorkerResponse = WorkerSuccess | WorkerFailure
