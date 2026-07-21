from decimal import Decimal
from pathlib import Path

import pytest

from vex_contracts.enums import OrderStatus
from vex_contracts.order_state_machine import (
    InvalidOrderTransition,
    apply_fill,
    transition_order,
)
from vex_contracts.orders import Fill, Order, OrderRequest
from vex_contracts.serialization import load_yaml


def build_order(project_root: Path) -> Order:
    request = OrderRequest.model_validate(
        load_yaml(project_root / "examples/configs/order_request.yaml")
    )
    return Order(order_id="order_internal_0001", request=request)


def test_order_lifecycle_reaches_filled(project_root: Path) -> None:
    order = build_order(project_root)
    accepted_time = order.request.created_time_ns + 10
    activated_time = order.request.created_time_ns + 20
    fill_time = order.request.created_time_ns + 30
    accepted = transition_order(order, OrderStatus.ACCEPTED, accepted_time)
    active = transition_order(accepted, OrderStatus.ACTIVE, activated_time)
    fill = Fill(
        fill_id="fill_0001",
        order_id=active.order_id,
        run_id=active.request.run_id,
        symbol=active.request.symbol,
        side=active.request.side,
        time_ns=fill_time,
        price_ticks=265000,
        volume_lots="0.50",
    )
    filled = apply_fill(active, fill)

    assert filled.status is OrderStatus.FILLED
    assert filled.filled_volume_lots == Decimal("0.50")
    assert filled.terminal_time_ns == fill_time


def test_terminal_order_rejects_transition(project_root: Path) -> None:
    order = build_order(project_root)
    cancelled_time = order.request.created_time_ns + 10
    cancelled = transition_order(order, OrderStatus.CANCELLED, cancelled_time)

    with pytest.raises(InvalidOrderTransition):
        transition_order(cancelled, OrderStatus.ACCEPTED, cancelled_time + 10)


def test_order_supports_deterministic_partial_fill(project_root: Path) -> None:
    order = build_order(project_root)
    accepted_time = order.request.created_time_ns + 10
    activated_time = order.request.created_time_ns + 20
    accepted = transition_order(order, OrderStatus.ACCEPTED, accepted_time)
    active = transition_order(accepted, OrderStatus.ACTIVE, activated_time)
    first_fill = Fill(
        fill_id="fill_0001",
        order_id=active.order_id,
        run_id=active.request.run_id,
        symbol=active.request.symbol,
        side=active.request.side,
        time_ns=order.request.created_time_ns + 30,
        price_ticks=265000,
        volume_lots="0.20",
    )
    partial = apply_fill(active, first_fill)
    second_fill = Fill(
        fill_id="fill_0002",
        order_id=partial.order_id,
        run_id=partial.request.run_id,
        symbol=partial.request.symbol,
        side=partial.request.side,
        time_ns=order.request.created_time_ns + 40,
        price_ticks=265010,
        volume_lots="0.30",
    )
    filled = apply_fill(partial, second_fill)

    assert partial.status is OrderStatus.PARTIALLY_FILLED
    assert filled.status is OrderStatus.FILLED
    assert filled.average_fill_price_ticks == Decimal("265006")
