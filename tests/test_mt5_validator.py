from pathlib import Path

from vex_contracts.mt5 import Mt5CompatibilitySnapshot, Mt5ValidationTolerance
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_json, load_yaml
from vex_contracts.symbol import SymbolProfile
from vex_mt5.validator import validate_snapshot


def load_fixture() -> tuple[Mt5CompatibilitySnapshot, SymbolProfile, BacktestRunConfig]:
    snapshot = Mt5CompatibilitySnapshot.model_validate(
        load_json(Path("examples/mt5/xauusd_offline_snapshot.json"))
    )
    profile = SymbolProfile.model_validate(load_yaml(Path("examples/configs/symbol_xauusd.yaml")))
    run = BacktestRunConfig.model_validate(load_yaml(Path("examples/configs/run_sma_cross.yaml")))
    return snapshot, profile, run


def test_offline_mt5_fixture_is_compatible() -> None:
    snapshot, profile, run = load_fixture()
    report = validate_snapshot(snapshot, (profile,), Mt5ValidationTolerance(), run)
    assert report.compatible
    assert report.failed_checks == 0
    assert report.passed_checks == 40
    assert all(check.status == "passed" for check in report.checks)


def test_profile_mismatch_is_reported() -> None:
    snapshot, profile, run = load_fixture()
    mismatched = profile.model_copy(update={"trade_contract_size": profile.trade_contract_size * 2})
    report = validate_snapshot(snapshot, (mismatched,), Mt5ValidationTolerance(), run)
    assert not report.compatible
    assert report.failed_checks >= 1
    assert any(check.check_id == "symbol_xauusd_trade_contract_size" for check in report.checks)
