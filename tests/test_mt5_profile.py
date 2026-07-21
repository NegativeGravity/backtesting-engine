from pathlib import Path

from vex_contracts.mt5 import Mt5CompatibilitySnapshot
from vex_contracts.serialization import load_json
from vex_mt5.profile import profile_from_snapshot


def test_profile_is_generated_from_symbol_snapshot() -> None:
    snapshot = Mt5CompatibilitySnapshot.model_validate(
        load_json(Path("examples/mt5/xauusd_offline_snapshot.json"))
    )
    profile = profile_from_snapshot(snapshot.symbols[0])
    assert profile.symbol == "XAUUSD"
    assert profile.profile_id.startswith("mt5_xauusd_")
    assert profile.trade_tick_size == snapshot.symbols[0].trade_tick_size
    assert profile.trade_contract_size == snapshot.symbols[0].trade_contract_size
    assert profile.metadata["source"] == "mt5_symbol_info"
