from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from strategies.yj_box_breakout.strategy import (
    ENTRY_REEVALUATE_AFTER_FLAT_TAG,
    ENTRY_REQUIRE_FLAT_TAG,
    EXECUTION_ACCOUNT_BASIS_TAG,
    EXECUTION_REWARD_RISK_TAG,
    EXECUTION_RISK_REWARD_ENABLED_TAG,
    INTRABAR_ENTRY_TARGET_ALLOWED_TAG,
    OCO_AMBIGUOUS_POLICY_TAG,
    STOP_AND_REVERSE_ACCOUNT_BASIS_TAG,
    STOP_AND_REVERSE_ENABLED_TAG,
    YjBoxBreakoutParameters,
    YjBoxBreakoutStrategy,
)
from vex_broker.simulator import BrokerSimulator
from vex_contracts.dataset import DatasetManifest
from vex_contracts.enums import OrderType, Side, TimeInForce
from vex_contracts.market import Bar
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.strategy import StrategyDescriptor
from vex_contracts.strategy_runtime import StrategyRuntimeConfig, SubmitOrderAction
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe
from vex_strategy.context import StrategyContext

NS = 1_000_000_000
TEHRAN = ZoneInfo("Asia/Tehran")


def ns(value: datetime) -> int:
    return int(value.timestamp() * NS)


def load_context_models(
    project_root: Path,
) -> tuple[BacktestRunConfig, StrategyDescriptor, StrategyRuntimeConfig, SymbolProfile]:
    root = project_root / "strategies" / "yj_box_breakout"
    return (
        BacktestRunConfig.model_validate(load_yaml(root / "run.yaml")),
        StrategyDescriptor.model_validate(load_yaml(root / "strategy.yaml")),
        StrategyRuntimeConfig.model_validate(load_yaml(root / "runtime.yaml")),
        SymbolProfile.model_validate(load_yaml(root / "symbol_xauusd_fractional.yaml")),
    )


def make_box_bar(sequence: int, opened: datetime) -> Bar:
    high = 1100 if sequence == 7 else 1075 + sequence
    low = 900 if sequence == 0 else 925 - sequence
    return Bar(
        symbol="XAUUSD",
        timeframe=Timeframe.M15,
        open_time_ns=ns(opened),
        close_time_ns=ns(opened + timedelta(minutes=15)),
        open_ticks=1000,
        high_ticks=high,
        low_ticks=low,
        close_ticks=1000,
        sequence=sequence,
    )


def test_yj_parameters_preserve_notebook_defaults() -> None:
    parameters = YjBoxBreakoutParameters()

    assert parameters.symbol == "XAUUSD"
    assert parameters.signal_timeframe is Timeframe.M15
    assert parameters.box_start_minute == 90
    assert parameters.box_end_minute == 210
    assert parameters.expected_box_bars == 8
    assert parameters.reward_risk_ratio == Decimal("1.5")
    assert parameters.session_timezone == "Asia/Tehran"
    assert parameters.allow_long is True
    assert parameters.allow_short is True
    assert parameters.allow_overlapping_daily_chains is True


def test_yj_dataset_and_session_clocks_are_explicit(project_root: Path) -> None:
    root = project_root / "strategies" / "yj_box_breakout"
    dataset = DatasetManifest.model_validate(load_yaml(root / "dataset.yaml"))
    run, descriptor, _, _ = load_context_models(project_root)

    assert dataset.dataset_id == "xauusd_mt5_yj_tehran"
    assert dataset.source_timezone == "Asia/Tehran"
    assert len(dataset.files) == 1
    assert dataset.files[0].timeframe is Timeframe.M15
    assert run.dataset.dataset_id == dataset.dataset_id
    assert run.dataset.version == dataset.version == "2"
    assert run.strategy.parameters["session_timezone"] == "Asia/Tehran"
    assert run.strategy.parameters["strict_box_validation"] is True
    assert run.start_time.isoformat() == "2025-01-02T01:00:00+03:30"
    assert run.end_time.isoformat() == "2026-07-13T13:30:00+03:30"
    assert descriptor.version == "1.3.0"


def test_yj_run_uses_notebook_parity_execution_profile(project_root: Path) -> None:
    run, _, _, profile = load_context_models(project_root)

    assert run.account.leverage == Decimal("1000000")
    assert run.account.allow_negative_balance is True
    assert run.risk.max_margin_usage_percent == Decimal("100")
    assert run.risk.max_open_positions == 512
    assert run.risk.max_symbol_positions == 512
    assert run.risk.allow_pyramiding is True
    assert run.execution.spread.points == 0
    assert run.execution.commission.mode.value == "none"
    assert profile.digits == 3
    assert profile.trade_tick_size == Decimal("0.001")
    assert profile.trade_tick_value == Decimal("0.10")
    assert profile.volume_min == Decimal("0.000000000001")
    assert profile.volume_step == Decimal("0.000000000001")
    assert profile.volume_max == Decimal("1000000000000")


def test_yj_draws_forming_box_before_session_is_complete(project_root: Path) -> None:
    run, descriptor, runtime, profile = load_context_models(project_root)
    broker = BrokerSimulator(run, {"XAUUSD": profile})
    parameters = YjBoxBreakoutParameters.model_validate(run.strategy.parameters)
    strategy = YjBoxBreakoutStrategy(parameters.model_dump(mode="json"))
    context = StrategyContext(
        run,
        descriptor,
        runtime,
        parameters,
        broker.state_snapshot,
    )
    context.update_cycle(ns(run.start_time), (), (), broker.state_snapshot, ())
    context.begin_callback()
    strategy.on_start(context)
    context.drain()

    opened = datetime(2025, 1, 3, 1, 30, tzinfo=TEHRAN).astimezone(UTC)
    bar = make_box_bar(0, opened)
    context.update_cycle(bar.close_time_ns, (bar,), (), broker.state_snapshot, ())
    context.begin_callback()
    strategy.on_bar(context, bar)
    output = context.drain()

    assert len(output.chart_commands) == 3
    commands = [command.model_dump(mode="json") for command in output.chart_commands]
    drawing_ids = {
        str(command.get("drawing", {}).get("drawing_id", ""))
        for command in commands
        if command.get("command_type") == "upsert_drawing"
    }
    assert drawing_ids == {
        "yj.box.2025-01-03",
        "yj.box.high.2025-01-03",
        "yj.box.low.2025-01-03",
    }
    rectangle = next(
        command["drawing"]
        for command in commands
        if command.get("drawing", {}).get("kind") == "rectangle"
    )
    assert "FORMING" in str(rectangle["label"])


def test_complete_box_emits_exact_oco_breakout_pair(project_root: Path) -> None:
    run, descriptor, runtime, profile = load_context_models(project_root)
    broker = BrokerSimulator(run, {"XAUUSD": profile})
    parameters = YjBoxBreakoutParameters.model_validate(run.strategy.parameters)
    strategy = YjBoxBreakoutStrategy(parameters.model_dump(mode="json"))
    context = StrategyContext(
        run,
        descriptor,
        runtime,
        parameters,
        broker.state_snapshot,
    )
    context.update_cycle(ns(run.start_time), (), (), broker.state_snapshot, ())
    context.begin_callback()
    strategy.on_start(context)
    context.drain()

    output = None
    start = datetime(2025, 1, 3, 1, 30, tzinfo=TEHRAN).astimezone(UTC)
    for sequence in range(8):
        bar = make_box_bar(sequence, start + timedelta(minutes=15 * sequence))
        context.update_cycle(
            bar.close_time_ns,
            (bar,),
            (),
            broker.state_snapshot,
            (),
        )
        context.begin_callback()
        strategy.on_bar(context, bar)
        output = context.drain()

    assert output is not None
    actions = [action for action in output.actions if isinstance(action, SubmitOrderAction)]
    assert len(actions) == 2
    by_side = {action.intent.side: action.intent for action in actions}
    long_intent = by_side[Side.BUY]
    short_intent = by_side[Side.SELL]

    assert long_intent.order_type is OrderType.STOP
    assert long_intent.price_ticks == 1100
    assert long_intent.stop_loss_ticks == 900
    assert long_intent.take_profit_ticks == 1400
    assert long_intent.volume_lots is None
    assert long_intent.time_in_force is TimeInForce.DAY
    assert long_intent.tags[OCO_AMBIGUOUS_POLICY_TAG] == "cancel_all"
    assert long_intent.tags[STOP_AND_REVERSE_ENABLED_TAG] == "true"
    assert long_intent.tags[EXECUTION_RISK_REWARD_ENABLED_TAG] == "true"
    assert long_intent.tags[EXECUTION_REWARD_RISK_TAG] == "1.5"
    assert long_intent.tags[EXECUTION_ACCOUNT_BASIS_TAG] == "balance"
    assert long_intent.tags[STOP_AND_REVERSE_ACCOUNT_BASIS_TAG] == "balance"
    assert ENTRY_REQUIRE_FLAT_TAG not in long_intent.tags
    assert ENTRY_REEVALUATE_AFTER_FLAT_TAG not in long_intent.tags
    assert long_intent.tags[INTRABAR_ENTRY_TARGET_ALLOWED_TAG] == "true"

    assert short_intent.order_type is OrderType.STOP
    assert short_intent.price_ticks == 900
    assert short_intent.stop_loss_ticks == 1100
    assert short_intent.take_profit_ticks == 600
    assert short_intent.volume_lots is None
    assert short_intent.time_in_force is TimeInForce.DAY
    assert short_intent.tags[OCO_AMBIGUOUS_POLICY_TAG] == "cancel_all"
    assert short_intent.tags[STOP_AND_REVERSE_ENABLED_TAG] == "true"
    assert short_intent.tags[EXECUTION_RISK_REWARD_ENABLED_TAG] == "true"
    assert short_intent.tags[EXECUTION_REWARD_RISK_TAG] == "1.5"
    assert short_intent.tags[EXECUTION_ACCOUNT_BASIS_TAG] == "balance"
    assert short_intent.tags[STOP_AND_REVERSE_ACCOUNT_BASIS_TAG] == "balance"
    assert ENTRY_REQUIRE_FLAT_TAG not in short_intent.tags
    assert ENTRY_REEVALUATE_AFTER_FLAT_TAG not in short_intent.tags
    assert short_intent.tags[INTRABAR_ENTRY_TARGET_ALLOWED_TAG] == "true"
    assert long_intent.tags["vex.oco.group"] == short_intent.tags["vex.oco.group"]
    tehran_midnight = datetime(2025, 1, 4, tzinfo=TEHRAN).astimezone(UTC)
    assert long_intent.expiration_time_ns == ns(tehran_midnight)
    assert short_intent.expiration_time_ns == ns(tehran_midnight)
    assert len(output.chart_commands) == 3



def test_tehran_session_does_not_treat_utc_0130_as_tehran_0130(project_root: Path) -> None:
    run, descriptor, runtime, profile = load_context_models(project_root)
    broker = BrokerSimulator(run, {"XAUUSD": profile})
    parameters = YjBoxBreakoutParameters.model_validate(run.strategy.parameters)
    strategy = YjBoxBreakoutStrategy(parameters.model_dump(mode="json"))
    context = StrategyContext(
        run,
        descriptor,
        runtime,
        parameters,
        broker.state_snapshot,
    )
    context.update_cycle(ns(run.start_time), (), (), broker.state_snapshot, ())
    context.begin_callback()
    strategy.on_start(context)
    context.drain()

    output = None
    wrong_utc_start = datetime(2025, 1, 2, 1, 30, tzinfo=UTC)
    for sequence in range(8):
        bar = make_box_bar(sequence, wrong_utc_start + timedelta(minutes=15 * sequence))
        context.update_cycle(bar.close_time_ns, (bar,), (), broker.state_snapshot, ())
        context.begin_callback()
        strategy.on_bar(context, bar)
        output = context.drain()

    assert output is not None
    assert not [action for action in output.actions if isinstance(action, SubmitOrderAction)]


def test_session_helpers_use_tehran_calendar_boundaries() -> None:
    strategy = YjBoxBreakoutStrategy(
        YjBoxBreakoutParameters().model_dump(mode="json")
    )
    utc_value = datetime(2025, 1, 1, 22, 0, tzinfo=UTC)

    local_value = strategy._session_datetime(ns(utc_value))

    assert local_value.date().isoformat() == "2025-01-02"
    assert (local_value.hour, local_value.minute) == (1, 30)
    expected_midnight = datetime(2025, 1, 3, tzinfo=TEHRAN).astimezone(UTC)
    assert strategy._next_midnight_ns(local_value.date()) == ns(expected_midnight)
    assert strategy._format_time(ns(utc_value)).endswith("+0330")



def test_notebook_parity_rejects_single_direction_configuration() -> None:
    with pytest.raises(ValueError, match="both long and short"):
        YjBoxBreakoutParameters(allow_short=False)


def test_partial_tehran_box_fails_in_exact_parity_mode(project_root: Path) -> None:
    run, descriptor, runtime, profile = load_context_models(project_root)
    broker = BrokerSimulator(run, {"XAUUSD": profile})
    parameters = YjBoxBreakoutParameters.model_validate(run.strategy.parameters)
    strategy = YjBoxBreakoutStrategy(parameters.model_dump(mode="json"))
    context = StrategyContext(
        run,
        descriptor,
        runtime,
        parameters,
        broker.state_snapshot,
    )
    context.update_cycle(ns(run.start_time), (), (), broker.state_snapshot, ())
    context.begin_callback()
    strategy.on_start(context)
    context.drain()

    first = datetime(2025, 1, 3, 1, 30, tzinfo=TEHRAN).astimezone(UTC)
    for sequence in range(2):
        bar = make_box_bar(sequence, first + timedelta(minutes=15 * sequence))
        context.update_cycle(bar.close_time_ns, (bar,), (), broker.state_snapshot, ())
        context.begin_callback()
        strategy.on_bar(context, bar)
        context.drain()

    next_day = make_box_bar(
        3,
        datetime(2025, 1, 4, 0, 0, tzinfo=TEHRAN).astimezone(UTC),
    )
    context.update_cycle(next_day.close_time_ns, (next_day,), (), broker.state_snapshot, ())
    context.begin_callback()
    with pytest.raises(RuntimeError, match="incomplete Tehran 01:30-03:30 box"):
        strategy.on_bar(context, next_day)


def test_completed_box_metadata_survives_strategy_state_pruning(project_root: Path) -> None:
    run, descriptor, runtime, profile = load_context_models(project_root)
    broker = BrokerSimulator(run, {"XAUUSD": profile})
    parameters = YjBoxBreakoutParameters.model_validate(run.strategy.parameters)
    strategy = YjBoxBreakoutStrategy(parameters.model_dump(mode="json"))
    context = StrategyContext(
        run,
        descriptor,
        runtime,
        parameters,
        broker.state_snapshot,
    )
    context.update_cycle(ns(run.start_time), (), (), broker.state_snapshot, ())
    context.begin_callback()
    strategy.on_start(context)
    context.drain()

    start = datetime(2025, 1, 3, 1, 30, tzinfo=TEHRAN).astimezone(UTC)
    for sequence in range(8):
        bar = make_box_bar(sequence, start + timedelta(minutes=15 * sequence))
        context.update_cycle(bar.close_time_ns, (bar,), (), broker.state_snapshot, ())
        context.begin_callback()
        strategy.on_bar(context, bar)
        context.drain()

    trade_date = datetime(2025, 1, 3, tzinfo=TEHRAN).date()
    assert trade_date in strategy._boxes
    strategy._prune_state(trade_date + timedelta(days=90))
    assert trade_date in strategy._boxes

    context.begin_callback()
    strategy._redraw_audit_box(context, trade_date)
    output = context.drain()
    drawing_ids = {
        command.model_dump(mode="json")["drawing"]["drawing_id"]
        for command in output.chart_commands
        if command.model_dump(mode="json").get("command_type") == "upsert_drawing"
    }
    assert drawing_ids == {
        "yj.box.2025-01-03",
        "yj.box.high.2025-01-03",
        "yj.box.low.2025-01-03",
    }
