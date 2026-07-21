from decimal import Decimal

from vex_contracts.enums import OrderType, PositionSide, Side, TimeInForce
from vex_contracts.strategy_runtime import (
    CancelOrderAction,
    ModifyOrderAction,
    ModifyPositionProtectionAction,
    OrderIntent,
    SubmitOrderAction,
)
from vex_contracts.timeframes import Timeframe
from vex_strategy.actions import StrategyOutputCollector
from vex_strategy.market import MarketDataView
from vex_strategy.portfolio import PortfolioView


class StrategyOrderApi:
    def __init__(
        self,
        collector: StrategyOutputCollector,
        market: MarketDataView,
        portfolio: PortfolioView,
        execution_timeframe: Timeframe,
    ) -> None:
        self._collector = collector
        self._market = market
        self._portfolio = portfolio
        self._execution_timeframe = execution_timeframe

    def market(
        self,
        symbol: str,
        side: Side,
        volume_lots: Decimal | str | int | float | None = None,
        stop_loss_ticks: int | None = None,
        take_profit_ticks: int | None = None,
        sizing_price_ticks: int | None = None,
        client_order_id: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        reference = sizing_price_ticks
        if volume_lots is None and reference is None:
            latest = self._market.latest(symbol, self._execution_timeframe)
            if latest is None:
                raise ValueError("risk-sized market orders require a market reference price")
            reference = latest.close_ticks
        return self._submit(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            volume_lots=volume_lots,
            sizing_price_ticks=reference,
            stop_loss_ticks=stop_loss_ticks,
            take_profit_ticks=take_profit_ticks,
            client_order_id=client_order_id,
            tags=tags,
        )

    def limit(
        self,
        symbol: str,
        side: Side,
        price_ticks: int,
        volume_lots: Decimal | str | int | float | None = None,
        stop_loss_ticks: int | None = None,
        take_profit_ticks: int | None = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        expiration_time_ns: int | None = None,
        client_order_id: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        return self._submit(
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            volume_lots=volume_lots,
            price_ticks=price_ticks,
            sizing_price_ticks=price_ticks,
            stop_loss_ticks=stop_loss_ticks,
            take_profit_ticks=take_profit_ticks,
            time_in_force=time_in_force,
            expiration_time_ns=expiration_time_ns,
            client_order_id=client_order_id,
            tags=tags,
        )

    def stop(
        self,
        symbol: str,
        side: Side,
        price_ticks: int,
        volume_lots: Decimal | str | int | float | None = None,
        stop_loss_ticks: int | None = None,
        take_profit_ticks: int | None = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        expiration_time_ns: int | None = None,
        client_order_id: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        return self._submit(
            symbol=symbol,
            side=side,
            order_type=OrderType.STOP,
            volume_lots=volume_lots,
            price_ticks=price_ticks,
            sizing_price_ticks=price_ticks,
            stop_loss_ticks=stop_loss_ticks,
            take_profit_ticks=take_profit_ticks,
            time_in_force=time_in_force,
            expiration_time_ns=expiration_time_ns,
            client_order_id=client_order_id,
            tags=tags,
        )

    def buy_market(
        self,
        symbol: str,
        volume_lots: Decimal | str | int | float | None = None,
        stop_loss_ticks: int | None = None,
        take_profit_ticks: int | None = None,
        sizing_price_ticks: int | None = None,
        client_order_id: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        return self.market(
            symbol,
            Side.BUY,
            volume_lots,
            stop_loss_ticks,
            take_profit_ticks,
            sizing_price_ticks,
            client_order_id,
            tags,
        )

    def sell_market(
        self,
        symbol: str,
        volume_lots: Decimal | str | int | float | None = None,
        stop_loss_ticks: int | None = None,
        take_profit_ticks: int | None = None,
        sizing_price_ticks: int | None = None,
        client_order_id: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        return self.market(
            symbol,
            Side.SELL,
            volume_lots,
            stop_loss_ticks,
            take_profit_ticks,
            sizing_price_ticks,
            client_order_id,
            tags,
        )

    def cancel(self, order_id: str, reason: str = "strategy_requested") -> str:
        action_id = self._collector.next_action_id()
        self._collector.append_action(
            CancelOrderAction(
                action_id=action_id,
                requested_time_ns=self._collector.current_time_ns,
                order_id=order_id,
                reason=reason,
            )
        )
        return action_id

    def modify(
        self,
        order_id: str,
        price_ticks: int | None = None,
        stop_loss_ticks: int | None = None,
        take_profit_ticks: int | None = None,
        expiration_time_ns: int | None = None,
    ) -> str:
        action_id = self._collector.next_action_id()
        self._collector.append_action(
            ModifyOrderAction(
                action_id=action_id,
                requested_time_ns=self._collector.current_time_ns,
                order_id=order_id,
                price_ticks=price_ticks,
                stop_loss_ticks=stop_loss_ticks,
                take_profit_ticks=take_profit_ticks,
                expiration_time_ns=expiration_time_ns,
            )
        )
        return action_id

    def modify_protection(
        self,
        position_id: str,
        stop_loss_ticks: int | None,
        take_profit_ticks: int | None,
    ) -> str:
        action_id = self._collector.next_action_id()
        self._collector.append_action(
            ModifyPositionProtectionAction(
                action_id=action_id,
                requested_time_ns=self._collector.current_time_ns,
                position_id=position_id,
                stop_loss_ticks=stop_loss_ticks,
                take_profit_ticks=take_profit_ticks,
            )
        )
        return action_id

    def close_position(
        self,
        position_id: str,
        volume_lots: Decimal | str | int | float | None = None,
        client_order_id: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        position = self._portfolio.position(position_id)
        if position is None:
            raise ValueError(f"position not found: {position_id}")
        volume = position.volume_lots if volume_lots is None else Decimal(str(volume_lots))
        side = Side.SELL if position.side is PositionSide.LONG else Side.BUY
        return self._submit(
            symbol=position.symbol,
            side=side,
            order_type=OrderType.MARKET,
            volume_lots=volume,
            reduce_only=True,
            position_id=position.position_id,
            client_order_id=client_order_id,
            tags=tags,
        )

    def _submit(
        self,
        *,
        symbol: str,
        side: Side,
        order_type: OrderType,
        volume_lots: Decimal | str | int | float | None,
        price_ticks: int | None = None,
        sizing_price_ticks: int | None = None,
        stop_loss_ticks: int | None = None,
        take_profit_ticks: int | None = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        expiration_time_ns: int | None = None,
        reduce_only: bool = False,
        position_id: str | None = None,
        client_order_id: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        resolved_client_order_id = client_order_id or self._collector.next_client_order_id()
        action_id = self._collector.next_action_id()
        self._collector.append_action(
            SubmitOrderAction(
                action_id=action_id,
                requested_time_ns=self._collector.current_time_ns,
                intent=OrderIntent(
                    client_order_id=resolved_client_order_id,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    volume_lots=(None if volume_lots is None else Decimal(str(volume_lots))),
                    price_ticks=price_ticks,
                    sizing_price_ticks=sizing_price_ticks,
                    stop_loss_ticks=stop_loss_ticks,
                    take_profit_ticks=take_profit_ticks,
                    time_in_force=time_in_force,
                    expiration_time_ns=expiration_time_ns,
                    reduce_only=reduce_only,
                    position_id=position_id,
                    tags=tags or {},
                ),
            )
        )
        return resolved_client_order_id
