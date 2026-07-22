from decimal import Decimal
from pathlib import Path

from vex_broker.advanced_orders import (
    ENTRY_REEVALUATE_AFTER_FLAT_TAG,
    ENTRY_REQUIRE_FLAT_TAG,
    EXECUTION_REWARD_RISK_TAG,
    EXECUTION_RISK_REWARD_ENABLED_TAG,
    INTRABAR_ENTRY_TARGET_ALLOWED_TAG,
    OCO_AMBIGUOUS_POLICY_TAG,
    OCO_GROUP_TAG,
    OCO_POLICY_CANCEL_ALL,
    STOP_AND_REVERSE_CHAIN_ID_TAG,
    STOP_AND_REVERSE_ENABLED_TAG,
    STOP_AND_REVERSE_REWARD_RISK_TAG,
    STOP_AND_REVERSE_STOP_TICKS_TAG,
)
from vex_broker.simulator import BrokerSimulator
from vex_contracts.enums import OrderStatus, OrderType, PositionSide, Side, TimeInForce
from vex_contracts.market import Bar
from vex_contracts.orders import OrderRequest
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe

NS = 1_000_000_000
BAR_SECONDS = 15 * 60


def load_yj_models(project_root: Path) -> tuple[BacktestRunConfig, SymbolProfile]:
    root = project_root / "strategies" / "yj_box_breakout"
    run = BacktestRunConfig.model_validate(load_yaml(root / "run.yaml"))
    profile = SymbolProfile.model_validate(load_yaml(root / "symbol_xauusd_fractional.yaml"))
    return run, profile


def make_bar(
    sequence: int,
    open_ticks: int,
    high_ticks: int,
    low_ticks: int,
    close_ticks: int,
) -> Bar:
    open_time_ns = sequence * BAR_SECONDS * NS
    return Bar(
        symbol="XAUUSD",
        timeframe=Timeframe.M15,
        open_time_ns=open_time_ns,
        close_time_ns=open_time_ns + BAR_SECONDS * NS,
        open_ticks=open_ticks,
        high_ticks=high_ticks,
        low_ticks=low_ticks,
        close_ticks=close_ticks,
        sequence=sequence,
    )


def make_breakout_order(
    run: BacktestRunConfig,
    *,
    client_order_id: str,
    side: Side,
    trigger_ticks: int,
    stop_ticks: int,
    target_ticks: int,
    reverse_stop_ticks: int,
    group: str = "yj-test-group",
) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        run_id=run.run_id,
        strategy_instance_id=run.strategy.instance_id,
        symbol="XAUUSD",
        side=side,
        order_type=OrderType.STOP,
        volume_lots=Decimal("5"),
        created_time_ns=0,
        price_ticks=trigger_ticks,
        stop_loss_ticks=stop_ticks,
        take_profit_ticks=target_ticks,
        time_in_force=TimeInForce.DAY,
        expiration_time_ns=86_400 * NS,
        tags={
            "strategy": "yj_box_breakout",
            OCO_GROUP_TAG: group,
            OCO_AMBIGUOUS_POLICY_TAG: OCO_POLICY_CANCEL_ALL,
            EXECUTION_RISK_REWARD_ENABLED_TAG: "true",
            EXECUTION_REWARD_RISK_TAG: "1.5",
            ENTRY_REQUIRE_FLAT_TAG: "true",
            ENTRY_REEVALUATE_AFTER_FLAT_TAG: "true",
            INTRABAR_ENTRY_TARGET_ALLOWED_TAG: "true",
            STOP_AND_REVERSE_ENABLED_TAG: "true",
            STOP_AND_REVERSE_STOP_TICKS_TAG: str(reverse_stop_ticks),
            STOP_AND_REVERSE_REWARD_RISK_TAG: "1.5",
            STOP_AND_REVERSE_CHAIN_ID_TAG: "test-chain",
        },
    )


def broker(project_root: Path) -> tuple[BrokerSimulator, BacktestRunConfig]:
    run, profile = load_yj_models(project_root)
    return BrokerSimulator(run, {"XAUUSD": profile}), run


def submit_pair(instance: BrokerSimulator, run: BacktestRunConfig) -> None:
    instance.submit_order(
        make_breakout_order(
            run,
            client_order_id="yj-long",
            side=Side.BUY,
            trigger_ticks=1100,
            stop_ticks=900,
            target_ticks=1400,
            reverse_stop_ticks=1100,
        )
    )
    instance.submit_order(
        make_breakout_order(
            run,
            client_order_id="yj-short",
            side=Side.SELL,
            trigger_ticks=900,
            stop_ticks=1100,
            target_ticks=600,
            reverse_stop_ticks=900,
        )
    )


def test_oco_cancels_both_entries_when_one_bar_breaks_both_box_sides(
    project_root: Path,
) -> None:
    instance, run = broker(project_root)
    submit_pair(instance, run)

    result = instance.process_bar(make_bar(1, 1000, 1120, 880, 1000))

    assert result.fills == ()
    assert result.positions == ()
    assert {order.status for order in instance.orders} == {OrderStatus.CANCELLED}
    reasons = {
        event.payload.get("reason")
        for event in result.events
        if event.event_type.value == "order.cancelled"
    }
    assert reasons == {"oco_intrabar_ambiguous"}


def test_gap_entry_recalculates_volume_and_target_from_actual_fill(
    project_root: Path,
) -> None:
    instance, run = broker(project_root)
    submit_pair(instance, run)

    result = instance.process_bar(make_bar(1, 1120, 1140, 1000, 1100))

    assert len(result.positions) == 1
    position = result.positions[0]
    assert position.side is PositionSide.LONG
    assert position.average_entry_price_ticks == Decimal("1120")
    assert position.stop_loss_ticks == 900
    assert position.take_profit_ticks == 1450
    assert position.volume_lots == Decimal("4.54545454")
    sibling = next(
        order for order in instance.orders if order.request.client_order_id == "yj-short"
    )
    assert sibling.status is OrderStatus.CANCELLED
    filled = next(
        order for order in instance.orders if order.request.client_order_id == "yj-long"
    )
    assert filled.status is OrderStatus.FILLED
    assert filled.revision >= 1
    assert filled.request.take_profit_ticks == 1450
    assert filled.request.volume_lots == Decimal("4.54545454")


def test_initial_stop_opens_one_reversal_and_reversal_cannot_exit_same_bar(
    project_root: Path,
) -> None:
    instance, run = broker(project_root)
    submit_pair(instance, run)
    instance.process_bar(make_bar(1, 1120, 1140, 1000, 1100))

    stop_result = instance.process_bar(make_bar(2, 880, 1150, 500, 700))

    assert len(stop_result.trades) == 1
    assert stop_result.trades[0].side is PositionSide.LONG
    assert stop_result.trades[0].exit_reason == "stop_loss"
    assert stop_result.trades[0].exit_price_ticks == Decimal("880")
    assert len(stop_result.positions) == 1
    reversal = stop_result.positions[0]
    assert reversal.side is PositionSide.SHORT
    assert reversal.average_entry_price_ticks == Decimal("880")
    assert reversal.stop_loss_ticks == 1100
    assert reversal.take_profit_ticks == 550
    assert reversal.volume_lots == Decimal("4.49586776")

    target_result = instance.process_bar(make_bar(3, 880, 900, 500, 600))

    assert target_result.positions == ()
    assert len(instance.trades) == 2
    assert instance.trades[1].side is PositionSide.SHORT
    assert instance.trades[1].exit_reason == "take_profit"
    assert instance.trades[1].exit_price_ticks == Decimal("550")
    generated = [
        order
        for order in instance.orders
        if order.request.tags.get("broker_generated") == "stop_and_reverse"
    ]
    assert len(generated) == 1


def test_close_all_positions_uses_last_close_and_end_of_data_reason(
    project_root: Path,
) -> None:
    instance, run = broker(project_root)
    submit_pair(instance, run)
    bar = make_bar(1, 1120, 1140, 1000, 1110)
    instance.process_bar(bar)

    result = instance.close_all_positions(bar.close_time_ns, "end_of_data")

    assert result.positions == ()
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "end_of_data"
    assert result.trades[0].exit_price_ticks == Decimal("1110")


def test_intrabar_entry_can_take_target_on_breakout_bar(project_root: Path) -> None:
    instance, run = broker(project_root)
    submit_pair(instance, run)

    result = instance.process_bar(make_bar(1, 1000, 1410, 950, 1300))

    assert result.positions == ()
    assert len(result.trades) == 1
    assert result.trades[0].side is PositionSide.LONG
    assert result.trades[0].entry_price_ticks == Decimal("1100")
    assert result.trades[0].exit_price_ticks == Decimal("1400")
    assert result.trades[0].exit_reason == "take_profit"


def test_require_flat_keeps_daily_breakout_pending_until_account_is_flat(
    project_root: Path,
) -> None:
    instance, run = broker(project_root)
    instance.submit_order(
        OrderRequest(
            client_order_id="existing-position",
            run_id=run.run_id,
            strategy_instance_id=run.strategy.instance_id,
            symbol="XAUUSD",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            volume_lots=Decimal("1"),
            created_time_ns=0,
        )
    )
    submit_pair(instance, run)

    first = instance.process_bar(make_bar(1, 1000, 1120, 950, 1050))

    assert len(first.positions) == 1
    assert all(
        order.status is OrderStatus.ACTIVE
        for order in instance.orders
        if order.request.client_order_id in {"yj-long", "yj-short"}
    )
    instance.close_all_positions(first.account_snapshot.timestamp_ns, "strategy_exit")

    second = instance.process_bar(make_bar(2, 1000, 1120, 950, 1100))

    assert len(second.positions) == 1
    assert second.positions[0].side is PositionSide.LONG


def test_deferred_daily_entry_is_reevaluated_on_the_bar_that_becomes_flat(
    project_root: Path,
) -> None:
    instance, run = broker(project_root)
    instance.submit_order(
        OrderRequest(
            client_order_id="existing-position",
            run_id=run.run_id,
            strategy_instance_id=run.strategy.instance_id,
            symbol="XAUUSD",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            volume_lots=Decimal("1"),
            created_time_ns=0,
            take_profit_ticks=1050,
        )
    )
    submit_pair(instance, run)
    instance.process_bar(make_bar(1, 1000, 1010, 990, 1000))

    result = instance.process_bar(make_bar(2, 1000, 1120, 950, 1100))

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "take_profit"
    assert len(result.positions) == 1
    assert result.positions[0].side is PositionSide.LONG
    assert result.positions[0].average_entry_price_ticks == Decimal("1100")
    assert result.positions[0].opened_time_ns == 3 * BAR_SECONDS * NS
