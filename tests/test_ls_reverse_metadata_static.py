from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRATEGY = ROOT / "strategies/ls_volume_delta/strategy.py"
CORE = ROOT / "strategies/ls_volume_delta/core.py"


def test_strategy_contains_cover_metadata_recovery() -> None:
    source = STRATEGY.read_text(encoding="utf-8")
    for token in (
        "_normalized_entry_tags",
        "resolve_reverse_chain_id",
        "STOP_AND_REVERSE_CHAIN_ID_TAG",
        "_signal_metadata_tags",
        "ls_cover_metadata_recovered",
        "ls_cover_trade_metadata_recovered",
    ):
        assert token in source


def test_core_has_unambiguous_chain_resolution() -> None:
    source = CORE.read_text(encoding="utf-8")
    assert "if len(known) == 1" in source
    assert "if len(matches) == 1" in source
    assert "return None" in source
