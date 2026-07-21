from decimal import Decimal
from pathlib import Path

import pytest

from vex_broker.exceptions import AmbiguousBarError, OrderRejectedError
from vex_broker.simulator import BrokerSimulator
from vex_contracts.enums import (
    IntrabarPolicy,
    OrderStatus,
    OrderType,
    PositionMode,
    PositionSide,
    Side,
    TimeInForce,
)
from vex_contracts.market import Bar
from vex_contracts.orders import OrderCancellationRequest, OrderModificationRequest, OrderRequest
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe

NS = 1_000_000_000


def load_models(project_root: Path) -> tuple[BacktestRunConfig, SymbolProfile]:
    run = BacktestRunConfig.model_validate(load_yaml(project_root / "examples/configs/run.yaml"))
    profile = SymbolProfile.model_validate(
        load_yaml(project_root / "examples/configs/symbol_xauusd.yaml")
    )
    return run, profile


def make_bar(
    sequence: int,
    open_ticks: int,
    high_ticks: int,
    low_ticks: int,
    close_ticks: int,
    source_spread_points: int = 0,
) -> Bar:
    open_time = sequence * 60 * NS
    return Bar(
        symbol="XAUUSD",
        timeframe=Timeframe.M1,
        open_time_ns=open_time,
        close_time_ns=open_time + 60 * NS,
        open_ticks=open_ticks,
        high_ticks=high_ticks,
        low_ticks=low_ticks,
        close_ticks=close_ticks,
        source_spread_points=source_spread_points,
        sequence=sequence,
    )


def make_order(
    run: BacktestRunConfig,
    client_order_id: str,
    side: Side,
    created_time_ns: int,
    volume: Decimal = Decimal("1"),
    order_type: OrderType = OrderType.MARKET,
    price_ticks: int | None = None,
    stop_loss_ticks: int | None = None,
    take_profit_ticks: int | None = None,
    reduce_only: bool = False,
    position_id: str | None = None,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        run_id=run.run_id,
        strategy_instance_id=run.strategy.instance_id,
        symbol="XAUUSD",
        side=side,
        order_type=order_type,
        volume_lots=volume,
        created_time_ns=created_time_ns,
        price_ticks=price_ticks,
        stop_loss_ticks=stop_loss_ticks,
        take_profit_ticks=take_profit_ticks,
        reduce_only=reduce_only,
        position_id=position_id,
    )


def simulator(project_root: Path, run: BacktestRunConfig | None = None) -> BrokerSimulator:
    loaded_run, profile = load_models(project_root)
    return BrokerSimulator(run or loaded_run, {"XAUUSD": profile})


def test_market_order_uses_ask_and_updates_account(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    broker.submit_order(make_order(run, "market_buy", Side.BUY, 60 * NS))

    result = broker.process_bar(make_bar(1, 260000, 260020, 259990, 260010))

    assert result.fills[0].price_ticks == 260007
    assert result.fills[0].commission == Decimal("3.5")
    assert result.positions[0].side is PositionSide.LONG
    assert result.account_snapshot is not None
    assert result.account_snapshot.balance == Decimal("99996.5")
    assert result.account_snapshot.equity == Decimal("99999.5")
    assert result.account_snapshot.margin == Decimal("2600.10")


def test_limit_order_gets_gap_price_improvement(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    broker.submit_order(
        make_order(
            run,
            "limit_buy",
            Side.BUY,
            60 * NS,
            order_type=OrderType.LIMIT,
            price_ticks=260000,
        )
    )

    result = broker.process_bar(make_bar(1, 259990, 260020, 259980, 260000))

    assert result.fills[0].price_ticks == 259997
    assert broker.orders[0].status is OrderStatus.FILLED


def test_stop_order_gaps_to_open(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    broker.submit_order(
        make_order(
            run,
            "stop_buy",
            Side.BUY,
            60 * NS,
            order_type=OrderType.STOP,
            price_ticks=260000,
        )
    )

    result = broker.process_bar(make_bar(1, 260010, 260030, 260000, 260020))

    assert result.fills[0].price_ticks == 260017


def test_conservative_intrabar_policy_selects_stop(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    broker.submit_order(
        make_order(
            run,
            "bracket_buy",
            Side.BUY,
            60 * NS,
            stop_loss_ticks=259900,
            take_profit_ticks=260100,
        )
    )

    result = broker.process_bar(make_bar(1, 260000, 260150, 259850, 260020))

    assert len(result.trades) == 1
    assert result.trades[0].exit_price_ticks == Decimal("259900")
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.trades[0].intrabar_ambiguous is True
    assert result.positions == ()


def test_reject_ambiguous_policy_raises(project_root: Path) -> None:
    run, _ = load_models(project_root)
    execution = run.execution.model_copy(
        update={"intrabar_policy": IntrabarPolicy.REJECT_AMBIGUOUS}
    )
    broker = simulator(project_root, run.model_copy(update={"execution": execution}))
    broker.submit_order(
        make_order(
            run,
            "ambiguous_buy",
            Side.BUY,
            60 * NS,
            stop_loss_ticks=259900,
            take_profit_ticks=260100,
        )
    )

    with pytest.raises(AmbiguousBarError):
        broker.process_bar(make_bar(1, 260000, 260150, 259850, 260020))


def test_stop_loss_gap_uses_bar_open(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    broker.submit_order(
        make_order(
            run,
            "gap_stop_buy",
            Side.BUY,
            60 * NS,
            stop_loss_ticks=259900,
        )
    )
    broker.process_bar(make_bar(1, 260000, 260020, 259950, 260000))

    result = broker.process_bar(make_bar(2, 259850, 259880, 259800, 259820))

    assert result.trades[0].exit_price_ticks == Decimal("259850")
    assert result.trades[0].exit_reason == "stop_loss"


def test_partial_close_resizes_protection_orders(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    broker.submit_order(
        make_order(
            run,
            "partial_entry",
            Side.BUY,
            60 * NS,
            stop_loss_ticks=259000,
            take_profit_ticks=261000,
        )
    )
    broker.process_bar(make_bar(1, 260000, 260010, 259990, 260000))
    position = broker.open_positions[0]
    old_protection_ids = {
        order.order_id
        for order in broker.orders
        if "broker_protection" in order.request.tags and order.status is OrderStatus.ACTIVE
    }
    broker.submit_order(
        make_order(
            run,
            "partial_exit",
            Side.SELL,
            120 * NS,
            volume=Decimal("0.4"),
            reduce_only=True,
            position_id=position.position_id,
        )
    )

    result = broker.process_bar(make_bar(2, 260100, 260120, 260080, 260100))

    assert result.positions[0].volume_lots == Decimal("0.6")
    assert result.trades[0].volume_lots == Decimal("0.4")
    active_protections = [
        order
        for order in broker.orders
        if "broker_protection" in order.request.tags and order.status is OrderStatus.ACTIVE
    ]
    assert {order.request.volume_lots for order in active_protections} == {Decimal("0.6")}
    assert old_protection_ids.isdisjoint({order.order_id for order in active_protections})


def test_netting_reversal_closes_and_opens_remainder(project_root: Path) -> None:
    run, _ = load_models(project_root)
    account = run.account.model_copy(update={"position_mode": PositionMode.NETTING})
    risk = run.risk.model_copy(update={"allow_pyramiding": True})
    netting_run = run.model_copy(update={"account": account, "risk": risk})
    broker = simulator(project_root, netting_run)
    broker.submit_order(make_order(netting_run, "net_long", Side.BUY, 60 * NS))
    broker.process_bar(make_bar(1, 260000, 260020, 259990, 260000))
    broker.submit_order(
        make_order(
            netting_run,
            "net_reverse",
            Side.SELL,
            120 * NS,
            volume=Decimal("1.5"),
        )
    )

    result = broker.process_bar(make_bar(2, 260100, 260120, 260080, 260100))

    assert len(result.trades) == 1
    assert len(result.positions) == 1
    assert result.positions[0].side is PositionSide.SHORT
    assert result.positions[0].volume_lots == Decimal("0.5")


def test_insufficient_margin_rejects_at_execution(project_root: Path) -> None:
    run, _ = load_models(project_root)
    account = run.account.model_copy(update={"initial_balance": Decimal("100")})
    risk = run.risk.model_copy(update={"max_margin_usage_percent": Decimal("100")})
    low_balance_run = run.model_copy(update={"account": account, "risk": risk})
    broker = simulator(project_root, low_balance_run)
    broker.submit_order(make_order(low_balance_run, "margin_reject", Side.BUY, 60 * NS))

    result = broker.process_bar(make_bar(1, 260000, 260010, 259990, 260000))

    assert result.fills == ()
    assert broker.orders[0].status is OrderStatus.REJECTED
    assert broker.orders[0].rejection_reason == "insufficient_free_margin"


def test_stop_out_liquidates_and_applies_negative_balance_protection(
    project_root: Path,
) -> None:
    run, _ = load_models(project_root)
    account = run.account.model_copy(update={"initial_balance": Decimal("1000")})
    risk = run.risk.model_copy(update={"max_margin_usage_percent": Decimal("100")})
    stopout_run = run.model_copy(update={"account": account, "risk": risk})
    broker = simulator(project_root, stopout_run)
    broker.submit_order(
        make_order(
            stopout_run,
            "stopout_entry",
            Side.BUY,
            60 * NS,
            volume=Decimal("0.3"),
        )
    )
    broker.process_bar(make_bar(1, 260000, 260010, 259990, 260000))

    result = broker.process_bar(make_bar(2, 250000, 250010, 249990, 250000))

    assert result.positions == ()
    assert result.trades[0].exit_reason == "stop_out"
    assert result.account_snapshot is not None
    assert result.account_snapshot.balance == Decimal("0")


def test_order_modification_and_cancellation(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    submitted = broker.submit_order(
        make_order(
            run,
            "modify_limit",
            Side.BUY,
            60 * NS,
            order_type=OrderType.LIMIT,
            price_ticks=259000,
        )
    )
    order_id = submitted.events[-1].payload["order_id"]
    assert isinstance(order_id, str)

    broker.modify_order(
        OrderModificationRequest(
            order_id=order_id,
            requested_time_ns=61 * NS,
            price_ticks=259100,
        )
    )
    broker.cancel_order(
        OrderCancellationRequest(
            order_id=order_id,
            requested_time_ns=62 * NS,
        )
    )

    order = next(item for item in broker.orders if item.order_id == order_id)
    assert order.request.price_ticks == 259100
    assert order.status is OrderStatus.CANCELLED


def test_position_sizing_uses_equity_and_stop_distance(project_root: Path) -> None:
    broker = simulator(project_root)

    volume = broker.size_position("XAUUSD", 260000, 259000)

    assert volume == Decimal("1")


def test_deterministic_event_ids_and_payloads(project_root: Path) -> None:
    run, _ = load_models(project_root)
    first = simulator(project_root, run)
    second = simulator(project_root, run)
    request = make_order(run, "deterministic", Side.BUY, 60 * NS)

    first_events = [
        *first.submit_order(request).events,
        *first.process_bar(make_bar(1, 260000, 260010, 259990, 260000)).events,
    ]
    second_events = [
        *second.submit_order(request).events,
        *second.process_bar(make_bar(1, 260000, 260010, 259990, 260000)).events,
    ]

    assert [item.model_dump(mode="json") for item in first_events] == [
        item.model_dump(mode="json") for item in second_events
    ]


def test_duplicate_client_order_is_rejected(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    request = make_order(run, "duplicate", Side.BUY, 60 * NS)
    broker.submit_order(request)

    second = broker.submit_order(request)

    assert second.events[-1].payload["status"] == "rejected"
    assert second.events[-1].payload["rejection_reason"] == "duplicate_client_order_id"


def test_cannot_cancel_filled_order(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    submitted = broker.submit_order(make_order(run, "filled_cancel", Side.BUY, 60 * NS))
    order_id = submitted.events[-1].payload["order_id"]
    assert isinstance(order_id, str)
    broker.process_bar(make_bar(1, 260000, 260010, 259990, 260000))

    with pytest.raises(OrderRejectedError):
        broker.cancel_order(OrderCancellationRequest(order_id=order_id, requested_time_ns=121 * NS))


def test_state_snapshot_and_report_are_reproducible(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    broker.submit_order(make_order(run, "report_order", Side.BUY, 60 * NS))
    broker.process_bar(make_bar(1, 260000, 260010, 259990, 260000))

    snapshot = broker.state_snapshot
    first = broker.build_report(1)
    second = broker.build_report(1)

    assert snapshot.account == broker.account_snapshot
    assert snapshot.event_sequence == first.event_count
    assert first == second
    assert first.deterministic_digest == second.deterministic_digest


def test_disabling_same_bar_exit_still_protects_existing_positions(
    project_root: Path,
) -> None:
    run, _ = load_models(project_root)
    execution = run.execution.model_copy(update={"allow_same_bar_exit_after_open_fill": False})
    configured = run.model_copy(update={"execution": execution})
    broker = simulator(project_root, configured)
    broker.submit_order(
        make_order(
            configured,
            "delayed_protection",
            Side.BUY,
            60 * NS,
            stop_loss_ticks=259900,
        )
    )

    first = broker.process_bar(make_bar(1, 260000, 260010, 259850, 260000))
    second = broker.process_bar(make_bar(2, 260000, 260010, 259850, 260000))

    assert first.trades == ()
    assert len(first.positions) == 1
    assert second.trades[0].exit_reason == "stop_loss"


def test_short_market_order_uses_bid_and_marks_against_ask(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    broker.submit_order(make_order(run, "market_short", Side.SELL, 60 * NS))

    result = broker.process_bar(make_bar(1, 260000, 260020, 259980, 259990))

    assert result.fills[0].price_ticks == 260000
    assert result.positions[0].current_price_ticks == 259997
    assert result.account_snapshot is not None
    assert result.account_snapshot.floating_pnl == Decimal("3")


def test_day_order_expires_before_activation(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    request = make_order(
        run,
        "expiring_limit",
        Side.BUY,
        60 * NS,
        order_type=OrderType.LIMIT,
        price_ticks=259000,
    ).model_copy(update={"time_in_force": TimeInForce.DAY, "expiration_time_ns": 120 * NS})
    request = OrderRequest.model_validate(request.model_dump())
    broker.submit_order(request)

    result = broker.process_bar(make_bar(2, 260000, 260010, 259990, 260000))

    assert result.fills == ()
    assert broker.orders[0].status is OrderStatus.EXPIRED


def test_stale_order_time_is_rejected(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    broker.process_bar(make_bar(1, 260000, 260010, 259990, 260000))

    result = broker.submit_order(make_order(run, "stale", Side.BUY, 60 * NS))

    assert result.events[-1].payload["rejection_reason"] == "stale_order_time"


def test_broker_owned_protection_cannot_be_cancelled_directly(project_root: Path) -> None:
    run, _ = load_models(project_root)
    broker = simulator(project_root, run)
    broker.submit_order(
        make_order(
            run,
            "protected_entry",
            Side.BUY,
            60 * NS,
            stop_loss_ticks=259000,
        )
    )
    broker.process_bar(make_bar(1, 260000, 260010, 259990, 260000))
    protection = next(order for order in broker.orders if "broker_protection" in order.request.tags)

    with pytest.raises(OrderRejectedError):
        broker.cancel_order(
            OrderCancellationRequest(
                order_id=protection.order_id,
                requested_time_ns=121 * NS,
            )
        )


def test_historical_spread_uses_each_bars_source_spread(project_root: Path) -> None:
    run, profile = load_models(project_root)
    payload = run.model_dump(mode="python")
    payload["execution"]["spread"] = {
        "mode": "historical",
        "fallback_points": 7,
        "minimum_points": 1,
        "maximum_points": 50,
    }
    historical_run = BacktestRunConfig.model_validate(payload)
    broker = BrokerSimulator(historical_run, {"XAUUSD": profile})
    broker.submit_order(make_order(historical_run, "historical_buy", Side.BUY, 60 * NS))

    result = broker.process_bar(
        make_bar(1, 260000, 260040, 259990, 260010, source_spread_points=20)
    )

    assert result.fills[0].price_ticks == 260020
    assert result.fills[0].spread_cost > Decimal("0")


def test_historical_spread_falls_back_for_zero_and_applies_bounds(project_root: Path) -> None:
    run, profile = load_models(project_root)
    payload = run.model_dump(mode="python")
    payload["execution"]["spread"] = {
        "mode": "historical",
        "fallback_points": 80,
        "use_fallback_when_zero": True,
        "minimum_points": 5,
        "maximum_points": 30,
    }
    historical_run = BacktestRunConfig.model_validate(payload)
    broker = BrokerSimulator(historical_run, {"XAUUSD": profile})
    broker.submit_order(make_order(historical_run, "historical_fallback", Side.BUY, 60 * NS))

    result = broker.process_bar(
        make_bar(1, 260000, 260050, 259990, 260010, source_spread_points=0)
    )

    assert result.fills[0].price_ticks == 260030
