from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vex_contracts.enums import (
    ChartMarkerPosition,
    ChartMarkerShape,
    ChartSeriesKind,
    EventType,
    PositionSide,
    Side,
)
from vex_contracts.events import EventEnvelope
from vex_contracts.json_types import JsonValue
from vex_contracts.market import Bar
from vex_contracts.orders import Order
from vex_contracts.positions import Position, Trade
from vex_contracts.timeframes import Timeframe
from vex_strategy.base import Strategy
from vex_strategy.context import StrategyContext


class SmaCrossParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = "XAUUSD"
    signal_timeframe: Timeframe = Timeframe.M5
    fast_period: int = Field(default=10, ge=2, le=200)
    slow_period: int = Field(default=30, ge=3, le=500)
    volume_lots: Decimal = Field(default=Decimal("0.10"), gt=0)
    stop_distance_ticks: int = Field(default=800, ge=1)
    reward_risk_ratio: Decimal = Field(default=Decimal("2"), gt=0)
    allow_long: bool = True
    allow_short: bool = True

    @model_validator(mode="after")
    def validate_periods(self) -> SmaCrossParameters:
        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be below slow_period")
        if not self.allow_long and not self.allow_short:
            raise ValueError("at least one trade direction must be enabled")
        return self


class SmaCrossStrategy(Strategy):
    parameter_model: ClassVar[type[BaseModel]] = SmaCrossParameters

    def __init__(self, parameters: dict[str, JsonValue]) -> None:
        super().__init__(parameters)
        self.pending_client_order_id: str | None = None
        self.active_position_id: str | None = None
        self.entry_time_ns: int | None = None
        self.entry_price_ticks: Decimal | None = None
        self.stop_price_ticks: int | None = None
        self.target_price_ticks: int | None = None
        self.signal_sequence = 0

    @property
    def config(self) -> SmaCrossParameters:
        return SmaCrossParameters.model_validate(self.parameters)

    def on_start(self, context: StrategyContext) -> None:
        context.chart.declare_pane("sma.main", "SMA Cross", overlay=True)
        context.chart.declare_series(
            "sma.fast",
            "sma.main",
            f"SMA {self.config.fast_period}",
            kind=ChartSeriesKind.LINE,
            color="#2962FF",
        )
        context.chart.declare_series(
            "sma.slow",
            "sma.main",
            f"SMA {self.config.slow_period}",
            kind=ChartSeriesKind.LINE,
            color="#FF9800",
        )
        context.log.info(
            "sma_cross_started",
            symbol=self.config.symbol,
            timeframe=self.config.signal_timeframe.value,
            fast_period=self.config.fast_period,
            slow_period=self.config.slow_period,
        )

    def on_bar(self, context: StrategyContext, bar: Bar) -> None:
        config = self.config
        if bar.symbol != config.symbol or bar.timeframe is not config.signal_timeframe:
            return
        history = context.market.history(
            config.symbol,
            config.signal_timeframe,
            config.slow_period + 1,
        )
        if len(history) < config.slow_period + 1:
            return
        closes = [item.close_ticks for item in history]
        previous_fast = self._average(closes[-config.fast_period - 1 : -1])
        current_fast = self._average(closes[-config.fast_period :])
        previous_slow = self._average(closes[-config.slow_period - 1 : -1])
        current_slow = self._average(closes[-config.slow_period :])
        context.chart.plot_scalar("sma.fast", current_fast, bar.close_time_ns)
        context.chart.plot_scalar("sma.slow", current_slow, bar.close_time_ns)
        bullish = previous_fast <= previous_slow and current_fast > current_slow
        bearish = previous_fast >= previous_slow and current_fast < current_slow
        if not bullish and not bearish:
            return
        self.signal_sequence += 1
        side = Side.BUY if bullish else Side.SELL
        context.chart.marker(
            f"sma.signal.{self.signal_sequence}",
            bar.symbol,
            bar.timeframe,
            bar.close_time_ns,
            ChartMarkerShape.ARROW_UP if bullish else ChartMarkerShape.ARROW_DOWN,
            ChartMarkerPosition.BELOW_BAR if bullish else ChartMarkerPosition.ABOVE_BAR,
            "#089981" if bullish else "#F23645",
            price_ticks=bar.close_ticks,
            text="Bullish SMA cross" if bullish else "Bearish SMA cross",
        )
        position = self._current_position(context)
        if position is not None:
            desired = PositionSide.LONG if bullish else PositionSide.SHORT
            if position.side is not desired:
                context.orders.close_position(
                    position.position_id,
                    client_order_id=f"sma_exit_{self.signal_sequence}",
                    tags={"strategy": "sma_cross", "reason": "opposite_signal"},
                )
            return
        if self.pending_client_order_id is not None:
            return
        if bullish and not config.allow_long:
            return
        if bearish and not config.allow_short:
            return
        stop_distance = config.stop_distance_ticks
        target_distance = int(Decimal(stop_distance) * config.reward_risk_ratio)
        if side is Side.BUY:
            stop = bar.close_ticks - stop_distance
            target = bar.close_ticks + target_distance
        else:
            stop = bar.close_ticks + stop_distance
            target = bar.close_ticks - target_distance
        client_order_id = f"sma_entry_{self.signal_sequence}"
        context.orders.market(
            bar.symbol,
            side,
            volume_lots=config.volume_lots,
            stop_loss_ticks=stop,
            take_profit_ticks=target,
            client_order_id=client_order_id,
            tags={"strategy": "sma_cross", "signal": side.value},
        )
        self.pending_client_order_id = client_order_id
        self.stop_price_ticks = stop
        self.target_price_ticks = target
        context.log.info(
            "sma_cross_entry_submitted",
            client_order_id=client_order_id,
            side=side.value,
            reference_ticks=bar.close_ticks,
            stop_ticks=stop,
            target_ticks=target,
        )

    def on_order_update(
        self,
        context: StrategyContext,
        event: EventEnvelope[dict[str, JsonValue]],
    ) -> None:
        if event.event_type is EventType.POSITION_OPENED:
            position = Position.model_validate(event.payload)
            if position.symbol != self.config.symbol:
                return
            self.active_position_id = position.position_id
            self.pending_client_order_id = None
            self.entry_time_ns = position.opened_time_ns
            self.entry_price_ticks = position.average_entry_price_ticks
            self.stop_price_ticks = position.stop_loss_ticks
            self.target_price_ticks = position.take_profit_ticks
            if self.stop_price_ticks is not None and self.target_price_ticks is not None:
                context.chart.risk_reward(
                    f"sma.trade.{position.position_id}",
                    position.position_id,
                    position.symbol,
                    self.config.signal_timeframe,
                    position.side,
                    position.opened_time_ns,
                    position.average_entry_price_ticks,
                    self.stop_price_ticks,
                    self.target_price_ticks,
                    label="SMA cross trade",
                )
            context.log.info(
                "sma_cross_position_opened",
                position_id=position.position_id,
                side=position.side.value,
            )
            return
        if event.event_type in {
            EventType.ORDER_REJECTED,
            EventType.ORDER_CANCELLED,
            EventType.ORDER_EXPIRED,
        }:
            order_payload = {
                key: value for key, value in event.payload.items() if key in Order.model_fields
            }
            order = Order.model_validate(order_payload)
            if order.request.client_order_id == self.pending_client_order_id:
                self.pending_client_order_id = None
                context.log.warning(
                    "sma_cross_entry_not_filled",
                    client_order_id=order.request.client_order_id,
                    status=order.status.value,
                )
            return
        if event.event_type is EventType.POSITION_CLOSED:
            trade_data = event.payload.get("trade")
            if not isinstance(trade_data, dict):
                return
            trade = Trade.model_validate(trade_data)
            if trade.symbol != self.config.symbol:
                return
            if (
                self.entry_time_ns is not None
                and self.entry_price_ticks is not None
                and self.stop_price_ticks is not None
                and self.target_price_ticks is not None
            ):
                context.chart.risk_reward(
                    f"sma.trade.{trade.position_id}",
                    trade.trade_id,
                    trade.symbol,
                    self.config.signal_timeframe,
                    trade.side,
                    self.entry_time_ns,
                    self.entry_price_ticks,
                    self.stop_price_ticks,
                    self.target_price_ticks,
                    exit_time_ns=trade.exit_time_ns,
                    exit_price_ticks=trade.exit_price_ticks,
                    label=f"Net PnL {trade.net_pnl}",
                )
            context.log.info(
                "sma_cross_position_closed",
                trade_id=trade.trade_id,
                net_pnl=float(trade.net_pnl),
                exit_reason=trade.exit_reason,
            )
            self.active_position_id = None
            self.entry_time_ns = None
            self.entry_price_ticks = None
            self.stop_price_ticks = None
            self.target_price_ticks = None

    def on_stop(self, context: StrategyContext, reason: str) -> None:
        context.log.info("sma_cross_stopped", reason=reason)

    def _current_position(self, context: StrategyContext) -> Position | None:
        positions = context.portfolio.positions(self.config.symbol)
        if not positions:
            self.active_position_id = None
            return None
        position = positions[0]
        self.active_position_id = position.position_id
        return position

    @staticmethod
    def _average(values: list[int]) -> Decimal:
        return Decimal(sum(values)) / Decimal(len(values))
