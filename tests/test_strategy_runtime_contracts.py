from decimal import Decimal

import pytest
from pydantic import ValidationError

from vex_contracts.enums import OrderType, Side
from vex_contracts.strategy_runtime import OrderIntent, StrategyRuntimeConfig


def test_strategy_runtime_history_limit_validation() -> None:
    with pytest.raises(ValidationError):
        StrategyRuntimeConfig(
            history_limit_per_series=100,
            warmup_bars_per_series=101,
        )


def test_order_intent_requires_reference_for_risk_sizing() -> None:
    with pytest.raises(ValidationError):
        OrderIntent(
            client_order_id="intent_without_reference",
            symbol="XAUUSD",
            side=Side.BUY,
            order_type=OrderType.MARKET,
        )


def test_order_intent_accepts_explicit_volume_without_reference() -> None:
    intent = OrderIntent(
        client_order_id="intent_fixed_volume",
        symbol="XAUUSD",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        volume_lots=Decimal("0.10"),
    )

    assert intent.volume_lots == Decimal("0.10")
