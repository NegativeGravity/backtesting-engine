from decimal import Decimal
from pathlib import Path

import pytest

from vex_broker.calculations import signed_price_pnl
from vex_broker.exceptions import BrokerConfigurationError, OrderRejectedError
from vex_broker.simulator import BrokerSimulator
from vex_broker.sizing import PositionSizer
from vex_contracts.enums import (
    EventType,
    IntrabarPolicy,
    OrderStatus,
    OrderType,
    PositionMode,
    PositionSide,
    Side,
)
from vex_contracts.execution import FixedSlippageConfig
from vex_contracts.market import Bar
from vex_contracts.orders import OrderModificationRequest, OrderRequest
from vex_contracts.risk import (
    FixedCashRiskSizingConfig,
    FixedLotSizingConfig,
    StrategyDefinedSizingConfig,
)
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import load_yaml
from vex_contracts.symbol import SymbolProfile
from vex_contracts.timeframes import Timeframe

NS = 1_000_000_000


def models(project_root: Path) -> tuple[BacktestRunConfig, SymbolProfile]:
    run = BacktestRunConfig.model_validate(load_yaml(project_root / "examples/configs/run.yaml"))
    profile = SymbolProfile.model_validate(
        load_yaml(project_root / "examples/configs/symbol_xauusd.yaml")
    )
    return run, profile


def broker(
    project_root: Path,
    run: BacktestRunConfig | None = None,
    profile: SymbolProfile | None = None,
) -> BrokerSimulator:
    loaded_run, loaded_profile = models(project_root)
    return BrokerSimulator(run or loaded_run, {"XAUUSD": profile or loaded_profile})


def bar(
    sequence: int,
    open_ticks: int,
    high_ticks: int,
    low_ticks: int,
    close_ticks: int,
) -> Bar:
    open_time_ns = sequence * 60 * NS
    return Bar(
        symbol="XAUUSD",
        timeframe=Timeframe.M1,
        open_time_ns=open_time_ns,
        close_time_ns=open_time_ns + 60 * NS,
        open_ticks=open_ticks,
        high_ticks=high_ticks,
        low_ticks=low_ticks,
        close_ticks=close_ticks,
        sequence=sequence,
    )


def order(
    run: BacktestRunConfig,
    client_id: str,
    side: Side,
    created_time_ns: int,
    order_type: OrderType = OrderType.MARKET,
    price_ticks: int | None = None,
    volume: Decimal = Decimal("1"),
    stop_loss_ticks: int | None = None,
    take_profit_ticks: int | None = None,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_id,
        run_id=run.run_id,
        strategy_instance_id=run.strategy.instance_id,
        symbol="XAUUSD",
        side=side,
        order_type=order_type,
        price_ticks=price_ticks,
        volume_lots=volume,
        created_time_ns=created_time_ns,
        stop_loss_ticks=stop_loss_ticks,
        take_profit_ticks=take_profit_ticks,
    )


def test_market_slippage_is_adverse(project_root: Path) -> None:
    run, _ = models(project_root)
    slippage = FixedSlippageConfig(market_order_points=3)
    execution = run.execution.model_copy(update={"slippage": slippage})
    configured = run.model_copy(update={"execution": execution})
    instance = broker(project_root, configured)
    instance.submit_order(order(configured, "slipped_buy", Side.BUY, 60 * NS))

    result = instance.process_bar(bar(1, 260000, 260010, 259990, 260000))

    assert result.fills[0].price_ticks == 260010
    assert result.fills[0].slippage_cost == Decimal("3")


def test_limit_slippage_never_crosses_limit(project_root: Path) -> None:
    run, _ = models(project_root)
    slippage = FixedSlippageConfig(limit_order_points=20)
    execution = run.execution.model_copy(update={"slippage": slippage})
    configured = run.model_copy(update={"execution": execution})
    instance = broker(project_root, configured)
    instance.submit_order(
        order(
            configured,
            "capped_limit",
            Side.BUY,
            60 * NS,
            order_type=OrderType.LIMIT,
            price_ticks=260000,
        )
    )

    result = instance.process_bar(bar(1, 259990, 260010, 259980, 260000))

    assert result.fills[0].price_ticks == 260000
    assert result.fills[0].price_ticks <= 260000


def test_optimistic_policy_selects_target(project_root: Path) -> None:
    run, _ = models(project_root)
    execution = run.execution.model_copy(update={"intrabar_policy": IntrabarPolicy.OPTIMISTIC})
    configured = run.model_copy(update={"execution": execution})
    instance = broker(project_root, configured)
    instance.submit_order(
        order(
            configured,
            "optimistic",
            Side.BUY,
            60 * NS,
            stop_loss_ticks=259900,
            take_profit_ticks=260100,
        )
    )

    result = instance.process_bar(bar(1, 260000, 260150, 259850, 260000))

    assert result.trades[0].exit_reason == "take_profit"
    assert result.trades[0].exit_price_ticks == Decimal("260100")


def test_nearest_to_open_selects_closest_level(project_root: Path) -> None:
    run, _ = models(project_root)
    execution = run.execution.model_copy(update={"intrabar_policy": IntrabarPolicy.NEAREST_TO_OPEN})
    configured = run.model_copy(update={"execution": execution})
    instance = broker(project_root, configured)
    instance.submit_order(
        order(
            configured,
            "nearest",
            Side.BUY,
            60 * NS,
            stop_loss_ticks=259980,
            take_profit_ticks=260100,
        )
    )

    result = instance.process_bar(bar(1, 260000, 260150, 259950, 260000))

    assert result.trades[0].exit_reason == "stop_loss"


def test_market_order_with_invalid_gap_bracket_is_rejected(project_root: Path) -> None:
    run, _ = models(project_root)
    instance = broker(project_root, run)
    instance.submit_order(
        order(
            run,
            "invalid_gap_bracket",
            Side.BUY,
            60 * NS,
            take_profit_ticks=260005,
        )
    )

    result = instance.process_bar(bar(1, 260000, 260010, 259990, 260000))

    assert result.fills == ()
    assert instance.orders[0].status is OrderStatus.REJECTED
    assert instance.orders[0].rejection_reason == "long take profit must be above entry"


def test_margin_call_without_stop_out(project_root: Path) -> None:
    run, _ = models(project_root)
    account = run.account.model_copy(update={"initial_balance": Decimal("10000")})
    risk = run.risk.model_copy(update={"max_margin_usage_percent": Decimal("100")})
    configured = run.model_copy(update={"account": account, "risk": risk})
    instance = broker(project_root, configured)
    instance.submit_order(order(configured, "margin_call", Side.BUY, 60 * NS))
    instance.process_bar(bar(1, 260000, 260010, 259990, 260000))

    result = instance.process_bar(bar(2, 252000, 252010, 251990, 252000))

    event_types = {event.event_type for event in result.events}
    assert EventType.ACCOUNT_MARGIN_CALL in event_types
    assert EventType.ACCOUNT_STOP_OUT not in event_types
    assert len(result.positions) == 1


def test_position_protection_modification_replaces_orders(project_root: Path) -> None:
    run, _ = models(project_root)
    instance = broker(project_root, run)
    instance.submit_order(
        order(run, "modify_protection", Side.BUY, 60 * NS, stop_loss_ticks=259000)
    )
    instance.process_bar(bar(1, 260000, 260010, 259990, 260000))
    position = instance.open_positions[0]
    old_order = next(
        item
        for item in instance.orders
        if item.request.tags.get("broker_protection") == "stop_loss"
    )

    result = instance.modify_position_protection(
        position.position_id,
        121 * NS,
        259500,
        261000,
    )

    replaced = next(item for item in instance.orders if item.order_id == old_order.order_id)
    assert replaced.status is OrderStatus.CANCELLED
    active = [
        item
        for item in instance.orders
        if "broker_protection" in item.request.tags and item.status is OrderStatus.ACTIVE
    ]
    assert {item.request.price_ticks for item in active} == {259500, 261000}
    assert result.positions[0].stop_loss_ticks == 259500
    assert result.positions[0].take_profit_ticks == 261000


def test_noop_order_modification_is_rejected(project_root: Path) -> None:
    run, _ = models(project_root)
    instance = broker(project_root, run)
    submitted = instance.submit_order(
        order(
            run,
            "noop_modify",
            Side.BUY,
            60 * NS,
            order_type=OrderType.LIMIT,
            price_ticks=259000,
        )
    )
    order_id = submitted.events[-1].payload["order_id"]
    assert isinstance(order_id, str)

    with pytest.raises(OrderRejectedError):
        instance.modify_order(
            OrderModificationRequest(order_id=order_id, requested_time_ns=61 * NS)
        )


def test_netting_same_side_increase_respects_pyramiding_policy(project_root: Path) -> None:
    run, _ = models(project_root)
    account = run.account.model_copy(update={"position_mode": PositionMode.NETTING})
    configured = run.model_copy(update={"account": account})
    instance = broker(project_root, configured)
    instance.submit_order(order(configured, "net_first", Side.BUY, 60 * NS))
    instance.process_bar(bar(1, 260000, 260010, 259990, 260000))
    instance.submit_order(order(configured, "net_second", Side.BUY, 120 * NS))

    result = instance.process_bar(bar(2, 260000, 260010, 259990, 260000))

    assert result.fills == ()
    rejected = next(
        item for item in instance.orders if item.request.client_order_id == "net_second"
    )
    assert rejected.status is OrderStatus.REJECTED
    assert rejected.rejection_reason == "pyramiding is disabled"


def test_bar_sequence_regression_is_rejected(project_root: Path) -> None:
    instance = broker(project_root)
    instance.process_bar(bar(1, 260000, 260010, 259990, 260000))

    with pytest.raises(BrokerConfigurationError):
        instance.process_bar(bar(1, 260000, 260010, 259990, 260000))


def test_fixed_and_cash_sizing_modes(project_root: Path) -> None:
    _, profile = models(project_root)

    fixed = PositionSizer.size(
        FixedLotSizingConfig(volume_lots=Decimal("0.537")),
        Decimal("100000"),
        260000,
        259000,
        profile,
    )
    cash = PositionSizer.size(
        FixedCashRiskSizingConfig(cash_amount=Decimal("250")),
        Decimal("100000"),
        260000,
        259000,
        profile,
    )
    strategy = PositionSizer.size(
        StrategyDefinedSizingConfig(),
        Decimal("100000"),
        260000,
        None,
        profile,
        Decimal("0.347"),
    )

    assert fixed == Decimal("0.53")
    assert cash == Decimal("0.25")
    assert strategy == Decimal("0.34")


def test_strategy_sizing_requires_requested_volume(project_root: Path) -> None:
    _, profile = models(project_root)

    with pytest.raises(OrderRejectedError):
        PositionSizer.size(
            StrategyDefinedSizingConfig(),
            Decimal("100000"),
            260000,
            None,
            profile,
        )


def test_currency_mismatch_is_rejected(project_root: Path) -> None:
    run, profile = models(project_root)
    mismatched = profile.model_copy(update={"currency_profit": "EUR"})

    with pytest.raises(BrokerConfigurationError):
        broker(project_root, run, mismatched)


@pytest.mark.parametrize(
    ("entry", "movement", "volume_steps"),
    [
        (100000, -5000, 1),
        (260000, -250, 25),
        (260000, 0, 100),
        (260000, 750, 50),
        (500000, 5000, 100),
    ],
)
def test_long_and_short_pnl_are_symmetric(
    project_root: Path,
    entry: int,
    movement: int,
    volume_steps: int,
) -> None:
    _, profile = models(project_root)
    volume = Decimal(volume_steps) / Decimal("100")
    exit_price = Decimal(entry + movement)

    long_pnl = signed_price_pnl(
        PositionSide.LONG,
        Decimal(entry),
        exit_price,
        volume,
        profile,
    )
    short_pnl = signed_price_pnl(
        PositionSide.SHORT,
        Decimal(entry),
        exit_price,
        volume,
        profile,
    )

    assert long_pnl == -short_pnl
