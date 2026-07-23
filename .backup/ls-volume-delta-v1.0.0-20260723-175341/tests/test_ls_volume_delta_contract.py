from pathlib import Path

from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.strategy import StrategyDescriptor


def test_ls_package_contract(project_root: Path) -> None:
    package = project_root / "strategies" / "ls_volume_delta"
    descriptor = StrategyDescriptor.model_validate(
        load_yaml(package / "strategy.yaml")
    )
    run = BacktestRunConfig.model_validate(load_yaml(package / "run.yaml"))

    assert descriptor.strategy_id == "ls_volume_delta"
    assert descriptor.version == "1.0.0"
    assert run.execution_timeframe.value == "M1"
    assert run.strategy.parameters["signal_timeframe"] == "M15"
    assert run.strategy.parameters["delta_source_timeframe"] == "M1"
    assert run.strategy.parameters["primary_reward_risk"] == "2"
    assert run.strategy.parameters["cover_reward_risk"] == "1"
    assert run.risk.max_open_positions == 1
    assert run.risk.allow_pyramiding is False


def test_ls_strategy_requires_broker_metadata(project_root: Path) -> None:
    positions = (
        project_root / "src" / "vex_contracts" / "positions.py"
    ).read_text(encoding="utf-8")
    simulator = (
        project_root / "src" / "vex_broker" / "simulator.py"
    ).read_text(encoding="utf-8")

    for token in ("entry_order_id", "entry_client_order_id", "entry_tags"):
        assert token in positions
    for token in (
        "entry_tags=dict(request.tags)",
        "entry_tags=dict(position.entry_tags)",
    ):
        assert token in simulator
