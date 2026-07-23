from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "strategies" / "ls_volume_delta"


def test_strategy_adapter_contains_required_execution_tags() -> None:
    source = (PACKAGE / "strategy.py").read_text(encoding="utf-8")
    for token in (
        "vex.execution_risk_reward.enabled",
        "vex.execution_risk_reward.ratio",
        "vex.stop_and_reverse.enabled",
        "vex.stop_and_reverse.stop_ticks",
        "vex.stop_and_reverse.reward_risk",
        '"trade_date"',
        '"chain_id"',
        '"leg"',
        'getattr(position, "entry_tags"',
        'getattr(trade, "entry_tags"',
    ):
        assert token in source
    assert "ChartMarkerShape.TRIANGLE" not in source
    assert "ChartMarkerShape.CIRCLE" not in source


def test_run_profile_is_causal_and_bounded() -> None:
    run = yaml.safe_load((PACKAGE / "run.yaml").read_text(encoding="utf-8"))
    parameters = run["strategy"]["parameters"]
    assert run["execution_timeframe"] == "M1"
    assert parameters["signal_timeframe"] == "M15"
    assert parameters["delta_source_timeframe"] == "M1"
    assert parameters["minimum_m2_bars"] == 7
    assert parameters["maximum_structure_age"] == 3
    assert parameters["risk_accounting_mode"] == "nominal"
    assert run["risk"]["max_open_positions"] == 1
    assert run["risk"]["allow_pyramiding"] is False
    assert run["execution"]["signal_execution_policy"] == "next_bar_open"


def test_package_is_disabled_until_real_data_is_installed() -> None:
    package = yaml.safe_load(
        (PACKAGE / "package.yaml").read_text(encoding="utf-8")
    )
    profile = yaml.safe_load(
        (PACKAGE / "symbol_us30usd.yaml").read_text(encoding="utf-8")
    )
    assert package["enabled"] is False
    assert profile["metadata"]["verification_status"].startswith("replace")
