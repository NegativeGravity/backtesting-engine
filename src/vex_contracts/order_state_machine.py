from decimal import Decimal

from vex_contracts.enums import OrderStatus
from vex_contracts.orders import Fill, Order


class InvalidOrderTransition(ValueError):
    pass


_TERMINAL_STATUSES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
}

_ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset(
        {OrderStatus.ACCEPTED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
    ),
    OrderStatus.ACCEPTED: frozenset(
        {OrderStatus.ACTIVE, OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.REJECTED}
    ),
    OrderStatus.ACTIVE: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.REJECTED,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.REJECTED,
        }
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


def transition_order(
    order: Order,
    target: OrderStatus,
    time_ns: int,
    rejection_reason: str | None = None,
) -> Order:
    if time_ns < order.request.created_time_ns:
        raise ValueError("transition time must not precede order creation")
    if not can_transition(order.status, target):
        raise InvalidOrderTransition(f"cannot transition order from {order.status} to {target}")
    updates: dict[str, object] = {
        "status": target,
        "revision": order.revision + 1,
    }
    if target is OrderStatus.ACCEPTED:
        updates["accepted_time_ns"] = time_ns
    if target is OrderStatus.ACTIVE:
        updates["activated_time_ns"] = time_ns
    if target in _TERMINAL_STATUSES:
        updates["terminal_time_ns"] = time_ns
    if target is OrderStatus.REJECTED:
        updates["rejection_reason"] = rejection_reason or "rejected"
    return Order.model_validate(order.model_dump() | updates)


def apply_fill(order: Order, fill: Fill) -> Order:
    if order.order_id != fill.order_id:
        raise ValueError("fill order_id does not match order")
    if fill.run_id != order.request.run_id:
        raise ValueError("fill run_id does not match order")
    if fill.symbol != order.request.symbol:
        raise ValueError("fill symbol does not match order")
    if fill.side is not order.request.side:
        raise ValueError("fill side does not match order")
    if fill.time_ns < order.request.created_time_ns:
        raise ValueError("fill time must not precede order creation")
    if order.status not in {OrderStatus.ACCEPTED, OrderStatus.ACTIVE, OrderStatus.PARTIALLY_FILLED}:
        raise InvalidOrderTransition(f"cannot fill order in status {order.status}")
    new_volume = order.filled_volume_lots + fill.volume_lots
    if new_volume > order.request.volume_lots:
        raise ValueError("fill exceeds remaining order volume")
    previous_notional = Decimal(order.average_fill_price_ticks or 0) * order.filled_volume_lots
    fill_notional = Decimal(fill.price_ticks) * fill.volume_lots
    average_price = (previous_notional + fill_notional) / new_volume
    target = (
        OrderStatus.FILLED
        if new_volume == order.request.volume_lots
        else OrderStatus.PARTIALLY_FILLED
    )
    updates: dict[str, object] = {
        "status": target,
        "revision": order.revision + 1,
        "filled_volume_lots": new_volume,
        "average_fill_price_ticks": average_price,
    }
    if target is OrderStatus.FILLED:
        updates["terminal_time_ns"] = fill.time_ns
    return Order.model_validate(order.model_dump() | updates)
