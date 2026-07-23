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
        "_validated_entry_tags",
        "cover_enabled",
    ):
        assert token in source
    assert "ChartMarkerShape.TRIANGLE" not in source
    assert "ChartMarkerShape.CIRCLE" not in source


def test_run_profile_is_causal_and_bounded() -> None:
    run = yaml.safe_load((PACKAGE / "run.yaml").read_text(encoding="utf-8"))
    parameters = run["strategy"]["parameters"]
    assert run["execution_timeframe"] == "M1"
    assert parameters["symbol"] == "US30"
    assert parameters["signal_timeframe"] == "M15"
    assert parameters["delta_source_timeframe"] == "M1"
    assert parameters["minimum_m2_bars"] == 7
    assert parameters["maximum_structure_age"] == 3
    assert parameters["risk_accounting_mode"] == "nominal"
    assert run["risk"]["max_open_positions"] == 1
    assert run["risk"]["allow_pyramiding"] is False
    assert run["execution"]["signal_execution_policy"] == "next_bar_open"


def test_package_targets_exact_us30_dataset() -> None:
    package = yaml.safe_load(
        (PACKAGE / "package.yaml").read_text(encoding="utf-8")
    )
    dataset = yaml.safe_load(
        (PACKAGE / "dataset.yaml").read_text(encoding="utf-8")
    )
    run = yaml.safe_load((PACKAGE / "run.yaml").read_text(encoding="utf-8"))

    assert package["enabled"] is True
    assert package["import_report_path"] == (
        "../../data/cache/us30_mt5_ls/1/import-report.json"
    )
    assert package["symbol_profile_paths"] == ["symbol_us30.yaml"]
    assert run["dataset"] == {"dataset_id": "us30_mt5_ls", "version": "1"}
    paths = {
        entry["timeframe"]: entry["relative_path"]
        for entry in dataset["files"]
    }
    assert paths["M1"].startswith("US30_M1_202501020101_202607222358")
    assert paths["M15"].startswith("US30_M15_202501020100_202607222345")



def test_package_import_report_resolves_from_package_directory() -> None:
    package = yaml.safe_load(
        (PACKAGE / "package.yaml").read_text(encoding="utf-8")
    )
    resolved = (PACKAGE / package["import_report_path"]).resolve()
    expected = (
        ROOT
        / "data"
        / "cache"
        / "us30_mt5_ls"
        / "1"
        / "import-report.json"
    ).resolve()
    assert resolved == expected
