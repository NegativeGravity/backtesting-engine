from decimal import Decimal

import pytest
from pydantic import ValidationError

from vex_contracts.positions import Trade


def test_trade_requires_exact_cost_attribution() -> None:
    trade = Trade(
        trade_id="trade_0001",
        position_id="position_0001",
        run_id="run_example_0001",
        strategy_instance_id="strategy_example_0001",
        symbol="XAUUSD",
        side="long",
        volume_lots="1",
        entry_time_ns=1,
        exit_time_ns=2,
        entry_price_ticks="200000",
        exit_price_ticks="201000",
        gross_pnl="1000",
        commission="7",
        spread_cost="5",
        slippage_cost="0",
        swap="0",
        net_pnl="988",
        exit_reason="take_profit",
    )

    assert trade.net_pnl == Decimal("988")


def test_trade_rejects_inconsistent_net_pnl() -> None:
    with pytest.raises(ValidationError):
        Trade(
            trade_id="trade_0001",
            position_id="position_0001",
            run_id="run_example_0001",
            strategy_instance_id="strategy_example_0001",
            symbol="XAUUSD",
            side="long",
            volume_lots="1",
            entry_time_ns=1,
            exit_time_ns=2,
            entry_price_ticks="200000",
            exit_price_ticks="201000",
            gross_pnl="1000",
            commission="7",
            spread_cost="5",
            slippage_cost="0",
            swap="0",
            net_pnl="1000",
            exit_reason="take_profit",
        )
