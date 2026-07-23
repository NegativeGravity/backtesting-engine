from __future__ import annotations

import importlib
import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_TEXT = str(PROJECT_ROOT)
if PROJECT_ROOT_TEXT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT_TEXT)

core = importlib.import_module("strategies.ls_volume_delta.core")
strategy_module = importlib.import_module("strategies.ls_volume_delta.strategy")

Candle = core.Candle
Direction = core.Direction
SetupKind = core.SetupKind
Signal = core.Signal
STOP_AND_REVERSE_CHAIN_ID_TAG = strategy_module.STOP_AND_REVERSE_CHAIN_ID_TAG
LsVolumeDeltaStrategy = strategy_module.LsVolumeDeltaStrategy


def _signal() -> Signal:
    return Signal(
        direction=Direction.LONG,
        setup_kind=SetupKind.LS,
        candle=Candle(
            open_time_ns=1_767_571_200_000_000_000,
            close_time_ns=1_767_572_100_000_000_000,
            open_ticks=42_000,
            high_ticks=42_100,
            low_ticks=41_900,
            close_ticks=42_050,
            volume=1_000,
        ),
        volume_delta=-350,
        m2_bar_count=7,
        stop_ticks=41_900,
        cover_stop_ticks=42_050,
        hunted_structure_id="low-1",
        hunted_structure_ticks=41_950,
        hunted_structure_time_ns=1_767_570_300_000_000_000,
    )


def test_minimal_broker_generated_cover_metadata_is_recovered() -> None:
    strategy = LsVolumeDeltaStrategy({})
    chain_id = "ls-2026-01-05-00001"
    strategy._signal_by_chain[chain_id] = _signal()

    normalized, recovered = strategy._normalized_entry_tags(
        {
            "broker_generated": "stop_and_reverse",
            "leg": "2",
            STOP_AND_REVERSE_CHAIN_ID_TAG: chain_id,
        },
        event_name="POSITION_OPENED",
        object_id="pos_cover",
        event_time_ns=1_767_572_160_000_000_000,
        entry_client_order_id=None,
    )

    assert recovered is True
    assert normalized["strategy"] == "ls_volume_delta"
    assert normalized["chain_id"] == chain_id
    assert normalized["trade_date"] == date(2026, 1, 5).isoformat()
    assert normalized["leg"] == "2"
    assert normalized["volume_delta"] == "-350"
    assert normalized["setup_kind"] == "ls"


def test_cover_metadata_uses_only_active_chain_when_broker_omits_chain() -> None:
    strategy = LsVolumeDeltaStrategy({})
    chain_id = "ls-2026-01-05-00001"
    strategy._signal_by_chain[chain_id] = _signal()

    normalized, recovered = strategy._normalized_entry_tags(
        {"broker_generated": "stop_and_reverse", "leg": "2"},
        event_name="POSITION_OPENED",
        object_id="pos_cover",
        event_time_ns=1_767_572_160_000_000_000,
        entry_client_order_id=None,
    )

    assert recovered is True
    assert normalized["chain_id"] == chain_id


def test_cover_metadata_does_not_guess_between_multiple_chains() -> None:
    strategy = LsVolumeDeltaStrategy({})
    strategy._signal_by_chain["ls-2026-01-05-00001"] = _signal()
    strategy._signal_by_chain["ls-2026-01-06-00002"] = _signal()

    with pytest.raises(RuntimeError, match="active_chains"):
        strategy._normalized_entry_tags(
            {"broker_generated": "stop_and_reverse", "leg": "2"},
            event_name="POSITION_OPENED",
            object_id="pos_cover",
            event_time_ns=1_767_572_160_000_000_000,
            entry_client_order_id=None,
        )
