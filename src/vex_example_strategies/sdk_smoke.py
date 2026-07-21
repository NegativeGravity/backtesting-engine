from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from vex_contracts.enums import (
    ChartMarkerPosition,
    ChartMarkerShape,
    ChartSeriesKind,
    EventType,
    PositionSide,
)
from vex_contracts.events import EventEnvelope
from vex_contracts.json_types import JsonValue
from vex_contracts.market import Bar
from vex_contracts.positions import Position, Trade
from vex_contracts.timeframes import Timeframe
from vex_strategy.base import Strategy
from vex_strategy.context import StrategyContext


class SdkSmokeParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = "XAUUSD"
    entry_after_bars: int = Field(default=2, ge=1)
    hold_bars: int = Field(default=20, ge=1)
    volume_lots: Decimal = Field(default=Decimal("0.10"), gt=0)
    stop_distance_ticks: int = Field(default=5000, ge=100)
    target_distance_ticks: int = Field(default=5000, ge=100)


class SdkSmokeStrategy(Strategy):
    parameter_model: ClassVar[type[BaseModel]] = SdkSmokeParameters

    def __init__(self, parameters: dict[str, JsonValue]) -> None:
        super().__init__(parameters)
        self.m1_bar_count = 0
        self.entry_submitted = False
        self.close_submitted = False
        self.position_id: str | None = None
        self.position_open_bar_count: int | None = None
        self.entry_time_ns: int | None = None
        self.entry_price_ticks: Decimal | None = None
        self.stop_price_ticks: int | None = None
        self.target_price_ticks: int | None = None

    @property
    def config(self) -> SdkSmokeParameters:
        return SdkSmokeParameters.model_validate(self.parameters)

    def on_start(self, context: StrategyContext) -> None:
        context.chart.declare_pane("sdk.main", "SDK Smoke", overlay=True)
        context.chart.declare_series(
            "sdk.close",
            "sdk.main",
            "M1 Close",
            kind=ChartSeriesKind.LINE,
            color="#2962FF",
        )
        context.log.info("strategy_started", symbol=self.config.symbol)

    def on_bar(self, context: StrategyContext, bar: Bar) -> None:
        if bar.symbol != self.config.symbol or bar.timeframe is not Timeframe.M1:
            return
        self.m1_bar_count += 1
        context.chart.plot_scalar("sdk.close", bar.close_ticks, bar.close_time_ns)
        if not self.entry_submitted and self.m1_bar_count >= self.config.entry_after_bars:
            self.entry_submitted = True
            reference = bar.close_ticks
            self.stop_price_ticks = reference - self.config.stop_distance_ticks
            self.target_price_ticks = reference + self.config.target_distance_ticks
            context.orders.buy_market(
                bar.symbol,
                volume_lots=self.config.volume_lots,
                stop_loss_ticks=self.stop_price_ticks,
                take_profit_ticks=self.target_price_ticks,
                client_order_id="sdk_smoke_entry",
                tags={"purpose": "strategy_sdk_smoke"},
            )
            context.chart.marker(
                "sdk.entry.signal",
                bar.symbol,
                bar.timeframe,
                bar.close_time_ns,
                ChartMarkerShape.ARROW_UP,
                ChartMarkerPosition.BELOW_BAR,
                "#089981",
                price_ticks=bar.close_ticks,
                text="Entry signal",
            )
            return
        if (
            self.position_id is not None
            and self.position_open_bar_count is not None
            and not self.close_submitted
            and self.m1_bar_count - self.position_open_bar_count >= self.config.hold_bars
        ):
            self.close_submitted = True
            context.orders.close_position(
                self.position_id,
                client_order_id="sdk_smoke_exit",
                tags={"purpose": "strategy_sdk_smoke"},
            )
            context.chart.marker(
                "sdk.exit.signal",
                bar.symbol,
                bar.timeframe,
                bar.close_time_ns,
                ChartMarkerShape.ARROW_DOWN,
                ChartMarkerPosition.ABOVE_BAR,
                "#F23645",
                price_ticks=bar.close_ticks,
                text="Exit signal",
            )

    def on_order_update(
        self,
        context: StrategyContext,
        event: EventEnvelope[dict[str, JsonValue]],
    ) -> None:
        if event.event_type is EventType.POSITION_OPENED:
            position = Position.model_validate(event.payload)
            self.position_id = position.position_id
            self.position_open_bar_count = self.m1_bar_count
            self.entry_time_ns = position.opened_time_ns
            self.entry_price_ticks = position.average_entry_price_ticks
            self.stop_price_ticks = position.stop_loss_ticks
            self.target_price_ticks = position.take_profit_ticks
            if self.stop_price_ticks is not None and self.target_price_ticks is not None:
                context.chart.risk_reward(
                    "sdk.trade.box",
                    position.position_id,
                    position.symbol,
                    Timeframe.M1,
                    PositionSide.LONG,
                    position.opened_time_ns,
                    position.average_entry_price_ticks,
                    self.stop_price_ticks,
                    self.target_price_ticks,
                    label="SDK smoke trade",
                )
            context.log.info("position_opened", position_id=position.position_id)
        if event.event_type is EventType.POSITION_CLOSED:
            trade_data = event.payload.get("trade")
            if not isinstance(trade_data, dict):
                return
            trade = Trade.model_validate(trade_data)
            if (
                self.entry_time_ns is not None
                and self.entry_price_ticks is not None
                and self.stop_price_ticks is not None
                and self.target_price_ticks is not None
            ):
                context.chart.risk_reward(
                    "sdk.trade.box",
                    trade.trade_id,
                    trade.symbol,
                    Timeframe.M1,
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
                "position_closed",
                trade_id=trade.trade_id,
                net_pnl=float(trade.net_pnl),
            )
            self.position_id = None

    def on_stop(self, context: StrategyContext, reason: str) -> None:
        context.log.info("strategy_stopped", reason=reason)
