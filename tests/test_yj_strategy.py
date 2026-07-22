from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from strategies.yj_box_breakout.strategy import (
    ENTRY_REEVALUATE_AFTER_FLAT_TAG,
    ENTRY_REQUIRE_FLAT_TAG,
    EXECUTION_REWARD_RISK_TAG,
    EXECUTION_RISK_REWARD_ENABLED_TAG,
    INTRABAR_ENTRY_TARGET_ALLOWED_TAG,
    OCO_AMBIGUOUS_POLICY_TAG,
    STOP_AND_REVERSE_ENABLED_TAG,
    YjBoxBreakoutParameters,
    YjBoxBreakoutStrategy,
)
from vex_broker.simulator import BrokerSimulator
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


def test_yj_run_uses_notebook_parity_execution_profile(project_root: Path) -> None:
    run, _, _, profile = load_context_models(project_root)

    assert run.account.leverage == Decimal("1000000")
    assert run.account.allow_negative_balance is True
    assert run.risk.max_margin_usage_percent == Decimal("100")
    assert run.execution.spread.points == 0
    assert run.execution.commission.mode.value == "none"
    assert profile.volume_min == Decimal("0.00000001")
    assert profile.volume_step == Decimal("0.00000001")
    assert profile.volume_max == Decimal("1000000")


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
    start = datetime(2025, 1, 2, 1, 30, tzinfo=UTC)
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
    assert long_intent.tags[ENTRY_REQUIRE_FLAT_TAG] == "true"
    assert long_intent.tags[ENTRY_REEVALUATE_AFTER_FLAT_TAG] == "true"
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
    assert short_intent.tags[ENTRY_REQUIRE_FLAT_TAG] == "true"
    assert short_intent.tags[ENTRY_REEVALUATE_AFTER_FLAT_TAG] == "true"
    assert short_intent.tags[INTRABAR_ENTRY_TARGET_ALLOWED_TAG] == "true"
    assert long_intent.tags["vex.oco.group"] == short_intent.tags["vex.oco.group"]
    assert long_intent.expiration_time_ns == ns(datetime(2025, 1, 3, tzinfo=UTC))
    assert short_intent.expiration_time_ns == ns(datetime(2025, 1, 3, tzinfo=UTC))
    assert len(output.chart_commands) == 3
