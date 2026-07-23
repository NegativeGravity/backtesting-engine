from __future__ import annotations

from decimal import Decimal

from vex_broker.models import PositionState
from vex_contracts.enums import PositionSide, PositionStatus
from vex_contracts.positions import Position, Trade


def test_position_contract_accepts_entry_tags() -> None:
    position = Position(
        position_id="position_1",
        run_id="run_1",
        strategy_instance_id="yj",
        symbol="XAUUSD",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        volume_lots=Decimal("1"),
        average_entry_price_ticks=Decimal("1000"),
        opened_time_ns=1,
        entry_order_id="order_1",
        entry_client_order_id="client_1",
        entry_tags={
            "trade_date": "2025-01-02",
            "chain_id": "2025-01-02-0001",
            "leg": "1",
        },
    )
    assert position.entry_tags["chain_id"] == "2025-01-02-0001"


def test_position_state_preserves_entry_tags() -> None:
    state = PositionState(
        position_id="position_1",
        run_id="run_1",
        strategy_instance_id="yj",
        symbol="XAUUSD",
        side="long",
        volume_lots=Decimal("1"),
        average_entry_price_ticks=Decimal("1000"),
        opened_time_ns=1,
        entry_order_id="order_1",
        entry_client_order_id="client_1",
        entry_tags={
            "trade_date": "2025-01-02",
            "chain_id": "2025-01-02-0001",
            "leg": "1",
        },
    )
    assert state.entry_tags["trade_date"] == "2025-01-02"


def test_trade_contract_preserves_entry_tags() -> None:
    trade = Trade(
        trade_id="trade_1",
        position_id="position_1",
        run_id="run_1",
        strategy_instance_id="yj",
        symbol="XAUUSD",
        side=PositionSide.LONG,
        volume_lots=Decimal("1"),
        entry_time_ns=1,
        exit_time_ns=2,
        entry_price_ticks=Decimal("1000"),
        exit_price_ticks=Decimal("1015"),
        entry_order_id="order_1",
        entry_client_order_id="client_1",
        entry_tags={
            "trade_date": "2025-01-02",
            "chain_id": "2025-01-02-0001",
            "leg": "1",
        },
        stop_loss_ticks=990,
        take_profit_ticks=1015,
        gross_pnl=Decimal("15"),
        commission=Decimal("0"),
        spread_cost=Decimal("0"),
        slippage_cost=Decimal("0"),
        swap=Decimal("0"),
        net_pnl=Decimal("15"),
        initial_risk=Decimal("10"),
        realized_r_multiple=Decimal("1.5"),
        exit_reason="take_profit",
    )
    assert trade.entry_tags["leg"] == "1"
