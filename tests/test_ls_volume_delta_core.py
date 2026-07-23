import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

CORE_PATH = Path(__file__).resolve().parents[1] / "strategies" / "ls_volume_delta" / "core.py"
SPEC = importlib.util.spec_from_file_location("ls_volume_delta_core", CORE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

Candle = MODULE.Candle
ClockAlignedM2Delta = MODULE.ClockAlignedM2Delta
Direction = MODULE.Direction
RiskGovernor = MODULE.RiskGovernor
resolve_reverse_chain_id = MODULE.resolve_reverse_chain_id
StructureLevel = MODULE.StructureLevel
StructureKind = MODULE.StructureKind
strategy_accounting_r = MODULE.strategy_accounting_r
SessionState = MODULE.SessionState
SetupKind = MODULE.SetupKind
SignalEngine = MODULE.SignalEngine

# Imported dynamically so these pure tests run without the VEX runtime installed.


def candle(
    index: int,
    open_ticks: int,
    high_ticks: int,
    low_ticks: int,
    close_ticks: int,
    volume: int = 10,
) -> Candle:
    minute = 60 * 1_000_000_000
    return Candle(
        index * minute,
        (index + 1) * minute,
        open_ticks,
        high_ticks,
        low_ticks,
        close_ticks,
        volume,
    )


def test_ls_formula_matches_pine_strict_inequalities() -> None:
    long_bar = candle(0, 100, 102, 90, 101)
    short_bar = candle(1, 100, 110, 98, 99)
    assert long_bar.long_ls is True
    assert long_bar.short_ls is False
    assert short_bar.short_ls is True
    assert short_bar.long_ls is False


def test_equality_is_not_ls_or_hunt() -> None:
    equal_shadow = candle(0, 100, 103, 98, 102)
    assert equal_shadow.long_ls is False


def test_clock_aligned_m2_delta_uses_official_direction_rule() -> None:
    delta = ClockAlignedM2Delta()
    delta.push_m1(candle(0, 100, 101, 99, 101, 7))
    built = delta.push_m1(candle(1, 101, 103, 100, 102, 5))
    assert built is not None
    assert built.direction == 1
    assert built.signed_volume == 12


def test_short_ls_requires_valid_hunted_high_and_positive_delta() -> None:
    engine = SignalEngine()
    first = candle(0, 100, 106, 99, 105)
    second = candle(15, 105, 107, 100, 101)
    engine.observe_without_signal(first, None)
    engine.observe_without_signal(second, first)
    signal_bar = candle(30, 102, 115, 101, 103)
    signal = engine.evaluate(
        signal_bar,
        second,
        volume_delta=100,
        m2_bar_count=7,
        session_high_before=110,
        session_low_before=90,
    )
    assert signal is not None
    assert signal.direction is Direction.SHORT
    assert signal.setup_kind is SetupKind.LS


def test_intervening_higher_wick_blocks_short_until_swept() -> None:
    engine = SignalEngine()
    first = candle(0, 100, 106, 99, 105)
    second = candle(15, 105, 107, 100, 101)
    blocker = candle(30, 101, 120, 100, 102)
    engine.observe_without_signal(first, None)
    engine.observe_without_signal(second, first)
    engine.observe_without_signal(blocker, second)
    unswept = candle(45, 102, 115, 101, 103)
    signal = engine.evaluate(
        unswept,
        blocker,
        volume_delta=100,
        m2_bar_count=7,
        session_high_before=121,
        session_low_before=90,
    )
    assert signal is None


def test_signal_candle_can_trade_level_before_close_invalidation() -> None:
    engine = SignalEngine()
    first = candle(0, 100, 106, 99, 105)
    second = candle(15, 105, 107, 100, 101)
    engine.observe_without_signal(first, None)
    engine.observe_without_signal(second, first)
    signal_bar = candle(30, 108, 115, 105, 106)
    signal = engine.evaluate(
        signal_bar,
        second,
        volume_delta=100,
        m2_bar_count=7,
        session_high_before=114,
        session_low_before=90,
    )
    assert signal is not None
    assert all(not item.valid for item in engine.highs)


def test_long_engulf_requires_new_session_low_and_negative_delta() -> None:
    engine = SignalEngine()
    previous = candle(0, 105, 106, 99, 100)
    engine.observe_without_signal(previous, None)
    current = candle(15, 100, 105, 94, 104)
    signal = engine.evaluate(
        current,
        previous,
        volume_delta=-200,
        m2_bar_count=7,
        session_high_before=110,
        session_low_before=95,
    )
    assert signal is not None
    assert signal.direction is Direction.LONG
    assert signal.setup_kind is SetupKind.ENGULF


def test_ls_and_engulf_same_direction_make_one_signal() -> None:
    engine = SignalEngine()
    top_a = candle(0, 100, 106, 99, 105)
    top_b = candle(15, 105, 107, 100, 101)
    previous = candle(30, 101, 108, 100, 104)
    engine.observe_without_signal(top_a, None)
    engine.observe_without_signal(top_b, top_a)
    engine.observe_without_signal(previous, top_b)
    current = candle(45, 104, 120, 102, 103)
    signal = engine.evaluate(
        current,
        previous,
        volume_delta=250,
        m2_bar_count=7,
        session_high_before=110,
        session_low_before=90,
    )
    assert signal is not None
    assert signal.setup_kind is SetupKind.LS_ENGULF


def test_risk_governor_counts_cover_and_enforces_five_positions() -> None:
    governor = RiskGovernor()
    day = date(2026, 6, 2)
    for _ in range(4):
        governor.position_opened(day)
    permission = governor.permission(day)
    assert permission.allowed is True
    assert permission.cover_enabled is False
    governor.position_opened(day)
    assert governor.permission(day).allowed is False


def test_two_primary_take_profits_stop_day() -> None:
    governor = RiskGovernor()
    day = date(2026, 6, 2)
    governor.trade_closed(day, realized_r=Decimal("2"), leg=1, take_profit=True)
    governor.trade_closed(day, realized_r=Decimal("2"), leg=1, take_profit=True)
    assert governor.permission(day).allowed is False


def test_plus_six_before_day_fifteen_pauses_until_day_fifteen() -> None:
    governor = RiskGovernor()
    early = date(2026, 6, 8)
    governor.trade_closed(early, realized_r=Decimal("6"), leg=1, take_profit=True)
    assert governor.permission(early).reason == "monthly_plus_six_pause"
    later = date(2026, 6, 15)
    assert governor.permission(later).allowed is True


def test_minus_seven_pauses_only_current_day() -> None:
    governor = RiskGovernor()
    day = date(2026, 6, 8)
    governor.trade_closed(day, realized_r=Decimal("-7"), leg=1, take_profit=False)
    assert governor.permission(day).allowed is False
    next_day = date(2026, 6, 9)
    assert governor.permission(next_day).allowed is True


def test_only_last_three_formed_structures_are_eligible() -> None:
    engine = SignalEngine(maximum_structure_age=3)
    engine.highs = [
        StructureLevel(
            structure_id=f"H-{index}",
            kind=StructureKind.HIGH,
            formed_index=index,
            formed_time_ns=index,
            wick_ticks=100 + index,
            body_break_ticks=500,
            intervening_extreme_ticks=100 + index,
            valid=index == 1,
        )
        for index in range(1, 5)
    ]
    active = engine._active(engine.highs)
    assert active == []


def test_m2_bar_crossing_parent_close_is_not_leaked() -> None:
    delta = ClockAlignedM2Delta()
    for index in range(15):
        delta.push_m1(candle(index, 100, 101, 99, 101, 1))
    parent = Candle(0, 15 * 60 * 1_000_000_000, 100, 110, 90, 101, 0)
    value, count = delta.delta_for(parent, minimum_bars=7)
    assert count == 7
    assert value == 14


def test_doji_m2_inherits_previous_direction_when_unchanged() -> None:
    delta = ClockAlignedM2Delta()
    delta.push_m1(candle(0, 100, 102, 99, 101, 2))
    first = delta.push_m1(candle(1, 101, 103, 100, 102, 3))
    assert first is not None and first.direction == 1
    delta.push_m1(candle(2, 102, 103, 101, 102, 4))
    second = delta.push_m1(candle(3, 102, 103, 101, 102, 5))
    assert second is not None
    assert second.direction == 1
    assert second.signed_volume == 9


def test_cover_is_disabled_when_primary_loss_reaches_minus_seven() -> None:
    governor = RiskGovernor()
    governor.trade_closed(
        date(2026, 6, 6),
        realized_r=Decimal("-3"),
        leg=1,
        take_profit=False,
    )
    governor.trade_closed(
        date(2026, 6, 7),
        realized_r=Decimal("-3"),
        leg=1,
        take_profit=False,
    )
    day = date(2026, 6, 8)
    permission = governor.permission(day)
    assert permission.allowed is True
    assert permission.cover_enabled is False


def test_nominal_strategy_accounting_ignores_cost_drift() -> None:
    assert strategy_accounting_r(
        exit_reason="take_profit",
        leg=1,
        broker_realized_r=Decimal("1.93"),
        primary_reward_risk=Decimal("2"),
        cover_reward_risk=Decimal("1"),
        mode="nominal",
    ) == Decimal("2")
    assert strategy_accounting_r(
        exit_reason="stop_loss",
        leg=2,
        broker_realized_r=Decimal("-1.08"),
        primary_reward_risk=Decimal("2"),
        cover_reward_risk=Decimal("1"),
        mode="nominal",
    ) == Decimal("-1")


def test_reverse_chain_id_prefers_broker_chain_tag() -> None:
    tags = {
        "broker_generated": "stop_and_reverse",
        "leg": "2",
        "vex.stop_and_reverse.chain_id": "ls-2026-01-05-00001",
    }
    assert (
        resolve_reverse_chain_id(
            tags,
            ["ls-2026-01-05-00001"],
        )
        == "ls-2026-01-05-00001"
    )


def test_reverse_chain_id_uses_single_active_chain() -> None:
    assert (
        resolve_reverse_chain_id(
            {"broker_generated": "stop_and_reverse", "leg": "2"},
            ["ls-2026-01-05-00001"],
        )
        == "ls-2026-01-05-00001"
    )


def test_reverse_chain_id_rejects_ambiguous_active_chains() -> None:
    assert (
        resolve_reverse_chain_id(
            {"broker_generated": "stop_and_reverse", "leg": "2"},
            ["ls-2026-01-05-00001", "ls-2026-01-06-00002"],
        )
        is None
    )


def test_reverse_chain_id_can_use_client_order_id() -> None:
    assert (
        resolve_reverse_chain_id(
            {"broker_generated": "stop_and_reverse", "leg": "2"},
            ["ls-2026-01-05-00001", "ls-2026-01-06-00002"],
            client_order_id="ls-2026-01-06-00002-cover",
        )
        == "ls-2026-01-06-00002"
    )
