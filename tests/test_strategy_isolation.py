from pathlib import Path

import pytest

from vex_broker.simulator import BrokerSimulator
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import StrategyRuntimeConfig, StrategyWarmupData
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_strategy.exceptions import StrategyExecutionError, StrategyTimeoutError
from vex_strategy.isolation import IsolatedStrategyProcess
from vex_strategy.protocol import WorkerStartRequest
from vex_strategy.runner import datetime_to_ns


def load_start_request(
    project_root: Path,
    entrypoint: str,
    startup_timeout_seconds: float,
) -> WorkerStartRequest:
    run = BacktestRunConfig.model_validate(
        load_yaml(project_root / "examples/configs/run_strategy_smoke.yaml")
    )
    descriptor = StrategyDescriptor.model_validate(
        load_yaml(project_root / "examples/configs/strategy_sdk_smoke.yaml")
    )
    profile = SymbolProfile.model_validate(
        load_yaml(project_root / "examples/configs/symbol_xauusd.yaml")
    )
    m1 = tuple(
        subscription for subscription in run.subscriptions if subscription.timeframe is Timeframe.M1
    )
    strategy = run.strategy.model_copy(update={"parameters": {}})
    run = run.model_copy(update={"subscriptions": m1, "strategy": strategy})
    descriptor = descriptor.model_copy(update={"subscriptions": m1, "entrypoint": entrypoint})
    broker = BrokerSimulator(run, {"XAUUSD": profile})
    return WorkerStartRequest(
        run_config=run,
        descriptor=descriptor,
        runtime_config=StrategyRuntimeConfig(
            startup_timeout_seconds=startup_timeout_seconds,
            warmup_bars_per_series=0,
        ),
        initial_snapshot=broker.state_snapshot,
        warmup=StrategyWarmupData(),
        start_time_ns=datetime_to_ns(run.start_time),
    )


def test_strategy_process_propagates_callback_failure(project_root: Path) -> None:
    process = IsolatedStrategyProcess(
        load_start_request(
            project_root,
            "vex_example_strategies.fault_injection:CrashingStartStrategy",
            5,
        )
    )

    with pytest.raises(StrategyExecutionError, match="intentional strategy failure"):
        process.start()


def test_strategy_process_enforces_startup_timeout(project_root: Path) -> None:
    process = IsolatedStrategyProcess(
        load_start_request(
            project_root,
            "vex_example_strategies.fault_injection:SlowStartStrategy",
            0.05,
        )
    )

    with pytest.raises(StrategyTimeoutError):
        process.start()
