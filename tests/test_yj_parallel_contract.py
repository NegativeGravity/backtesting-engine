from __future__ import annotations

from pathlib import Path

from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.strategy import StrategyDescriptor


def test_yj_parallel_daily_chains_are_the_primary_profile(project_root: Path) -> None:
    root = project_root / "strategies" / "yj_box_breakout"
    run = BacktestRunConfig.model_validate(load_yaml(root / "run.yaml"))
    descriptor = StrategyDescriptor.model_validate(load_yaml(root / "strategy.yaml"))

    assert run.strategy.version == "1.7.1"
    assert descriptor.version == "1.7.1"
    assert run.account.position_mode.value == "hedging"
    assert run.strategy.parameters["allow_overlapping_daily_chains"] is True
    assert descriptor.default_parameters["allow_overlapping_daily_chains"] is True
    assert run.risk.allow_pyramiding is True
    assert run.risk.max_open_positions >= 2
    assert run.risk.max_symbol_positions >= 2


def test_yj_strategy_source_contains_chain_isolation_guards(project_root: Path) -> None:
    source = (project_root / "strategies" / "yj_box_breakout" / "strategy.py").read_text(
        encoding="utf-8"
    )

    required_tokens = (
        "allow_overlapping_daily_chains",
        "if not config.allow_overlapping_daily_chains",
        "_position_identity",
        "position.entry_tags",
        '"chain_id"',
        '"trade_date"',
        '"leg"',
        "STOP_AND_REVERSE_ACCOUNT_BASIS_TAG",
        "EXECUTION_ACCOUNT_BASIS_TAG",
    )
    missing = [token for token in required_tokens if token not in source]
    assert not missing, f"YJ strategy is missing parallel-chain guards: {missing}"

    assert "_awaiting_reversal: tuple[date, str] | None" not in source


def test_yj_broker_contract_preserves_chain_identity(project_root: Path) -> None:
    positions_source = (project_root / "src" / "vex_contracts" / "positions.py").read_text(
        encoding="utf-8"
    )
    simulator_source = (project_root / "src" / "vex_broker" / "simulator.py").read_text(
        encoding="utf-8"
    )

    for token in (
        "entry_order_id",
        "entry_client_order_id",
        "entry_tags",
    ):
        assert token in positions_source
        assert token in simulator_source

    for token in (
        "entry_tags=dict(request.tags)",
        "entry_tags=dict(position.entry_tags)",
        'if key in {"strategy", "chain_id", "trade_date"}',
    ):
        assert token in simulator_source
