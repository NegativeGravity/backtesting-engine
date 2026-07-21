from collections.abc import Iterable

from vex_contracts.broker import BrokerStateSnapshot
from vex_contracts.enums import EventType, OrderStatus, PositionSide
from vex_contracts.events import EventEnvelope
from vex_contracts.json_types import JsonValue
from vex_contracts.orders import Order
from vex_contracts.positions import AccountSnapshot, Position, Trade


class PortfolioView:
    def __init__(self, snapshot: BrokerStateSnapshot) -> None:
        self._snapshot = snapshot
        self._trades: list[Trade] = []

    @property
    def account(self) -> AccountSnapshot:
        return self._snapshot.account

    @property
    def timestamp_ns(self) -> int:
        return self._snapshot.timestamp_ns

    def update(
        self,
        snapshot: BrokerStateSnapshot,
        events: Iterable[EventEnvelope[dict[str, JsonValue]]],
    ) -> None:
        self._snapshot = snapshot
        for event in events:
            if event.event_type not in {
                EventType.POSITION_CLOSED,
                EventType.POSITION_LIQUIDATED,
            }:
                continue
            trade_data = event.payload.get("trade")
            if isinstance(trade_data, dict):
                self._trades.append(Trade.model_validate(trade_data))

    def positions(
        self,
        symbol: str | None = None,
        side: PositionSide | None = None,
    ) -> tuple[Position, ...]:
        return tuple(
            position
            for position in self._snapshot.positions
            if (symbol is None or position.symbol == symbol)
            and (side is None or position.side is side)
        )

    def position(self, position_id: str) -> Position | None:
        return next(
            (
                position
                for position in self._snapshot.positions
                if position.position_id == position_id
            ),
            None,
        )

    def orders(
        self,
        symbol: str | None = None,
        status: OrderStatus | None = None,
    ) -> tuple[Order, ...]:
        return tuple(
            order
            for order in self._snapshot.orders
            if (symbol is None or order.request.symbol == symbol)
            and (status is None or order.status is status)
        )

    def order(self, order_id: str) -> Order | None:
        return next((order for order in self._snapshot.orders if order.order_id == order_id), None)

    def trades(self, symbol: str | None = None) -> tuple[Trade, ...]:
        return tuple(trade for trade in self._trades if symbol is None or trade.symbol == symbol)

    def last_trade(self, symbol: str | None = None) -> Trade | None:
        trades = self.trades(symbol)
        return trades[-1] if trades else None
