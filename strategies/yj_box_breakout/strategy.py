from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vex_contracts.enums import (
    ChartLineStyle,
    ChartMarkerPosition,
    ChartMarkerShape,
    EventType,
    PositionSide,
    Side,
    TimeInForce,
)
from vex_contracts.events import EventEnvelope
from vex_contracts.json_types import JsonValue
from vex_contracts.market import Bar
from vex_contracts.orders import Order
from vex_contracts.positions import Position, Trade
from vex_contracts.timeframes import Timeframe
from vex_strategy.base import Strategy
from vex_strategy.context import StrategyContext

OCO_GROUP_TAG = "vex.oco.group"
OCO_AMBIGUOUS_POLICY_TAG = "vex.oco.ambiguous_policy"
STOP_AND_REVERSE_ENABLED_TAG = "vex.stop_and_reverse.enabled"
STOP_AND_REVERSE_STOP_TICKS_TAG = "vex.stop_and_reverse.stop_ticks"
STOP_AND_REVERSE_REWARD_RISK_TAG = "vex.stop_and_reverse.reward_risk"
STOP_AND_REVERSE_CHAIN_ID_TAG = "vex.stop_and_reverse.chain_id"
STOP_AND_REVERSE_ACCOUNT_BASIS_TAG = "vex.stop_and_reverse.account_basis"
EXECUTION_RISK_REWARD_ENABLED_TAG = "vex.execution_risk_reward.enabled"
EXECUTION_REWARD_RISK_TAG = "vex.execution_risk_reward.ratio"
EXECUTION_ACCOUNT_BASIS_TAG = "vex.execution_risk_reward.account_basis"
ENTRY_REQUIRE_FLAT_TAG = "vex.entry.require_flat"
ENTRY_REEVALUATE_AFTER_FLAT_TAG = "vex.entry.reevaluate_after_flat"
INTRABAR_ENTRY_TARGET_ALLOWED_TAG = "vex.intrabar_entry.target_allowed"

NANOSECONDS_PER_SECOND = 1_000_000_000


@dataclass(slots=True)
class BoxState:
    trade_date: date
    start_time_ns: int
    end_time_ns: int
    high_ticks: int
    low_ticks: int
    bar_count: int
    submitted: bool = False


@dataclass(slots=True)
class TradeVisualState:
    trade_date: date
    chain_id: str
    leg_number: int
    side: PositionSide
    entry_time_ns: int
    entry_price_ticks: Decimal
    stop_price_ticks: int
    target_price_ticks: int


class YjBoxBreakoutParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = "XAUUSD"
    signal_timeframe: Timeframe = Timeframe.M15
    box_start_minute: int = Field(default=90, ge=0, le=1439)
    box_end_minute: int = Field(default=210, ge=1, le=1440)
    expected_box_bars: int = Field(default=8, ge=1, le=96)
    reward_risk_ratio: Decimal = Field(default=Decimal("1.5"), gt=0)
    session_timezone: str = Field(default="Asia/Tehran", min_length=1, max_length=128)
    allow_long: bool = True
    allow_short: bool = True
    draw_box: bool = True
    strict_box_validation: bool = True
    allow_overlapping_daily_chains: bool = True

    @model_validator(mode="after")
    def validate_strategy(self) -> YjBoxBreakoutParameters:
        if self.signal_timeframe is not Timeframe.M15:
            raise ValueError("signal_timeframe must be M15 for this strategy")
        if self.box_end_minute <= self.box_start_minute:
            raise ValueError("box_end_minute must be after box_start_minute")
        duration = self.box_end_minute - self.box_start_minute
        if duration % 15 != 0:
            raise ValueError("box duration must be divisible by 15 minutes")
        if duration // 15 != self.expected_box_bars:
            raise ValueError("expected_box_bars must match the configured box duration")
        if not self.allow_long or not self.allow_short:
            raise ValueError("notebook parity requires both long and short breakouts")
        try:
            ZoneInfo(self.session_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("session_timezone must be a valid IANA timezone") from exc
        return self


class YjBoxBreakoutStrategy(Strategy):
    parameter_model: ClassVar[type[BaseModel]] = YjBoxBreakoutParameters

    def __init__(self, parameters: dict[str, JsonValue]) -> None:
        super().__init__(parameters)
        self._bars_by_date: dict[date, dict[int, Bar]] = {}
        self._boxes: dict[date, BoxState] = {}
        self._chain_ids_by_date: dict[date, str] = {}
        self._position_visuals: dict[str, TradeVisualState] = {}
        self._chain_sequence = 0
        self._session_zone = ZoneInfo(self.config.session_timezone)
        self._last_trade_date: date | None = None

    @property
    def config(self) -> YjBoxBreakoutParameters:
        return YjBoxBreakoutParameters.model_validate(self.parameters)

    def on_start(self, context: StrategyContext) -> None:
        context.chart.declare_pane("yj.main", "YJ Box Breakout", overlay=True)
        context.log.info(
            "yj_box_breakout_started",
            symbol=self.config.symbol,
            timeframe=self.config.signal_timeframe.value,
            box_start_minute=self.config.box_start_minute,
            box_end_minute=self.config.box_end_minute,
            expected_box_bars=self.config.expected_box_bars,
            reward_risk=float(self.config.reward_risk_ratio),
            session_timezone=self.config.session_timezone,
            two_sided_breakout=self.config.allow_long and self.config.allow_short,
            strict_box_validation=self.config.strict_box_validation,
            allow_overlapping_daily_chains=self.config.allow_overlapping_daily_chains,
        )

    def on_bar(self, context: StrategyContext, bar: Bar) -> None:
        config = self.config
        if bar.symbol != config.symbol or bar.timeframe is not config.signal_timeframe:
            return

        opened = self._session_datetime(bar.open_time_ns)
        trade_date = opened.date()
        minute = opened.hour * 60 + opened.minute

        if self._last_trade_date is not None and trade_date != self._last_trade_date:
            self._validate_box_session(context, self._last_trade_date)

        self._last_trade_date = trade_date
        self._prune_state(trade_date)

        if config.box_start_minute <= minute < config.box_end_minute:
            day_bars = self._bars_by_date.setdefault(trade_date, {})
            day_bars[minute] = bar
            if minute == config.box_end_minute - 15:
                self._finalize_box(context, trade_date)
            elif config.draw_box:
                self._draw_forming_box(context, trade_date)

    def on_order_update(
        self,
        context: StrategyContext,
        event: EventEnvelope[dict[str, JsonValue]],
    ) -> None:
        if event.event_type is EventType.ORDER_REJECTED:
            self._handle_reversal_rejection(context, event)

        if event.event_type is EventType.POSITION_OPENED:
            self._position_opened(context, event)
            return

        if event.event_type in {
            EventType.POSITION_CLOSED,
            EventType.POSITION_LIQUIDATED,
        }:
            self._position_closed(context, event)

    def on_stop(self, context: StrategyContext, reason: str) -> None:
        if reason == "completed" and self._last_trade_date is not None:
            self._validate_box_session(context, self._last_trade_date)

        context.log.info(
            "yj_box_breakout_stopped",
            reason=reason,
            tracked_boxes=len(self._boxes),
            active_visuals=len(self._position_visuals),
        )

    def _finalize_box(self, context: StrategyContext, trade_date: date) -> None:
        config = self.config
        day_bars = self._bars_by_date.get(trade_date, {})
        expected_minutes = tuple(
            range(config.box_start_minute, config.box_end_minute, 15)
        )
        missing_minutes = tuple(
            minute for minute in expected_minutes if minute not in day_bars
        )

        if missing_minutes:
            self._handle_incomplete_box(
                context,
                trade_date,
                len(day_bars),
                missing_minutes,
            )
            return

        ordered = tuple(day_bars[minute] for minute in expected_minutes)
        high_ticks = max(bar.high_ticks for bar in ordered)
        low_ticks = min(bar.low_ticks for bar in ordered)

        if high_ticks <= low_ticks:
            context.log.warning(
                "yj_box_invalid",
                trade_date=trade_date.isoformat(),
                high_ticks=high_ticks,
                low_ticks=low_ticks,
            )
            return

        box = BoxState(
            trade_date=trade_date,
            start_time_ns=ordered[0].open_time_ns,
            end_time_ns=ordered[-1].close_time_ns,
            high_ticks=high_ticks,
            low_ticks=low_ticks,
            bar_count=len(ordered),
        )
        self._boxes[trade_date] = box

        if config.draw_box:
            self._draw_box(context, box)

        self._submit_breakout_pair(context, box)

    def _validate_box_session(
        self,
        context: StrategyContext,
        trade_date: date,
    ) -> None:
        day_bars = self._bars_by_date.get(trade_date, {})
        if not day_bars or trade_date in self._boxes:
            return

        expected_minutes = tuple(
            range(
                self.config.box_start_minute,
                self.config.box_end_minute,
                15,
            )
        )
        missing_minutes = tuple(
            minute for minute in expected_minutes if minute not in day_bars
        )

        if missing_minutes:
            self._handle_incomplete_box(
                context,
                trade_date,
                len(day_bars),
                missing_minutes,
            )

    def _handle_incomplete_box(
        self,
        context: StrategyContext,
        trade_date: date,
        observed_bars: int,
        missing_minutes: tuple[int, ...],
    ) -> None:
        missing_labels = tuple(
            f"{minute // 60:02d}:{minute % 60:02d}" for minute in missing_minutes
        )
        missing_text = ",".join(missing_labels)

        if self.config.draw_box:
            self._delete_box_drawings(context, trade_date)

        if self.config.strict_box_validation:
            raise RuntimeError(
                "incomplete Tehran 01:30-03:30 box for "
                f"{trade_date.isoformat()}: observed={observed_bars}, "
                f"missing={missing_text}"
            )

        context.log.warning(
            "yj_box_incomplete",
            trade_date=trade_date.isoformat(),
            observed_bars=observed_bars,
            expected_bars=self.config.expected_box_bars,
            missing_minutes=missing_text,
            missing_count=len(missing_labels),
        )

    def _submit_breakout_pair(self, context: StrategyContext, box: BoxState) -> None:
        config = self.config
        self._chain_sequence += 1
        chain_id = f"{box.trade_date.isoformat()}-{self._chain_sequence:04d}"
        expiration_time_ns = self._next_midnight_ns(box.trade_date)
        distance = box.high_ticks - box.low_ticks
        target_distance = int(
            (Decimal(distance) * config.reward_risk_ratio).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        )
        oco_group = f"yj-entry-{chain_id}"
        self._chain_ids_by_date[box.trade_date] = chain_id

        common_tags = {
            "strategy": "yj_box_breakout",
            "chain_id": chain_id,
            "trade_date": box.trade_date.isoformat(),
            "leg": "1",
            OCO_GROUP_TAG: oco_group,
            OCO_AMBIGUOUS_POLICY_TAG: "cancel_all",
            STOP_AND_REVERSE_ENABLED_TAG: "true",
            STOP_AND_REVERSE_REWARD_RISK_TAG: str(config.reward_risk_ratio),
            STOP_AND_REVERSE_CHAIN_ID_TAG: chain_id,
            STOP_AND_REVERSE_ACCOUNT_BASIS_TAG: "balance",
            EXECUTION_RISK_REWARD_ENABLED_TAG: "true",
            EXECUTION_REWARD_RISK_TAG: str(config.reward_risk_ratio),
            EXECUTION_ACCOUNT_BASIS_TAG: "balance",
            INTRABAR_ENTRY_TARGET_ALLOWED_TAG: "true",
        }

        if not config.allow_overlapping_daily_chains:
            common_tags[ENTRY_REQUIRE_FLAT_TAG] = "true"
            common_tags[ENTRY_REEVALUATE_AFTER_FLAT_TAG] = "true"

        if config.allow_long:
            context.orders.stop(
                config.symbol,
                Side.BUY,
                price_ticks=box.high_ticks,
                volume_lots=None,
                stop_loss_ticks=box.low_ticks,
                take_profit_ticks=box.high_ticks + target_distance,
                time_in_force=TimeInForce.DAY,
                expiration_time_ns=expiration_time_ns,
                client_order_id=f"yj-long-{chain_id}",
                tags=common_tags
                | {
                    "direction": "long",
                    STOP_AND_REVERSE_STOP_TICKS_TAG: str(box.high_ticks),
                },
            )

        if config.allow_short:
            context.orders.stop(
                config.symbol,
                Side.SELL,
                price_ticks=box.low_ticks,
                volume_lots=None,
                stop_loss_ticks=box.high_ticks,
                take_profit_ticks=box.low_ticks - target_distance,
                time_in_force=TimeInForce.DAY,
                expiration_time_ns=expiration_time_ns,
                client_order_id=f"yj-short-{chain_id}",
                tags=common_tags
                | {
                    "direction": "short",
                    STOP_AND_REVERSE_STOP_TICKS_TAG: str(box.low_ticks),
                },
            )

        box.submitted = True
        context.log.info(
            "yj_breakout_orders_submitted",
            trade_date=box.trade_date.isoformat(),
            chain_id=chain_id,
            box_high_ticks=box.high_ticks,
            box_low_ticks=box.low_ticks,
            expiration_time_ns=expiration_time_ns,
        )

    def _position_opened(
        self,
        context: StrategyContext,
        event: EventEnvelope[dict[str, JsonValue]],
    ) -> None:
        position = Position.model_validate(event.payload)
        if position.symbol != self.config.symbol:
            return
        if position.stop_loss_ticks is None or position.take_profit_ticks is None:
            return

        trade_date, chain_id, leg_number = self._position_identity(position)
        visual = TradeVisualState(
            trade_date=trade_date,
            chain_id=chain_id,
            leg_number=leg_number,
            side=position.side,
            entry_time_ns=position.opened_time_ns,
            entry_price_ticks=position.average_entry_price_ticks,
            stop_price_ticks=position.stop_loss_ticks,
            target_price_ticks=position.take_profit_ticks,
        )
        self._position_visuals[position.position_id] = visual
        self._redraw_audit_box(context, trade_date)

        context.chart.risk_reward(
            f"yj.trade.{position.position_id}",
            position.position_id,
            position.symbol,
            self.config.signal_timeframe,
            position.side,
            position.opened_time_ns,
            position.average_entry_price_ticks,
            position.stop_loss_ticks,
            position.take_profit_ticks,
            label=(
                f"YJ {trade_date.isoformat()} | CHAIN {chain_id} | "
                f"LEG {leg_number} {position.side.value.upper()} | "
                f"OPEN {self._format_time(position.opened_time_ns)}"
            ),
            z_index=20,
        )
        context.chart.marker(
            f"yj.entry.{position.position_id}",
            position.symbol,
            self.config.signal_timeframe,
            position.opened_time_ns,
            (
                ChartMarkerShape.ARROW_UP
                if position.side is PositionSide.LONG
                else ChartMarkerShape.ARROW_DOWN
            ),
            (
                ChartMarkerPosition.BELOW_BAR
                if position.side is PositionSide.LONG
                else ChartMarkerPosition.ABOVE_BAR
            ),
            "#089981" if position.side is PositionSide.LONG else "#F23645",
            price_ticks=position.average_entry_price_ticks,
            text=(
                f"{trade_date.isoformat()} L{leg_number} "
                f"{position.side.value.upper()}"
            ),
            z_index=30,
        )
        context.log.info(
            "yj_position_opened",
            position_id=position.position_id,
            entry_order_id=position.entry_order_id or "",
            chain_id=chain_id,
            trade_date=trade_date.isoformat(),
            leg_number=leg_number,
            side=position.side.value,
            entry_ticks=float(position.average_entry_price_ticks),
            stop_ticks=position.stop_loss_ticks,
            target_ticks=position.take_profit_ticks,
            concurrent_positions=len(
                context.portfolio.positions(self.config.symbol)
            ),
        )

    def _position_closed(
        self,
        context: StrategyContext,
        event: EventEnvelope[dict[str, JsonValue]],
    ) -> None:
        trade_payload = event.payload.get("trade")
        if not isinstance(trade_payload, dict):
            return

        trade = Trade.model_validate(trade_payload)
        if trade.symbol != self.config.symbol:
            return

        visual = self._position_visuals.pop(trade.position_id, None)
        if visual is None:
            return

        self._redraw_audit_box(context, visual.trade_date)
        hit_label = self._exit_label(trade.exit_reason)
        r_text = (
            ""
            if trade.realized_r_multiple is None
            else f" | {trade.realized_r_multiple:.2f}R"
        )

        context.chart.risk_reward(
            f"yj.trade.{trade.position_id}",
            trade.trade_id,
            trade.symbol,
            self.config.signal_timeframe,
            trade.side,
            visual.entry_time_ns,
            visual.entry_price_ticks,
            visual.stop_price_ticks,
            visual.target_price_ticks,
            exit_time_ns=trade.exit_time_ns,
            exit_price_ticks=trade.exit_price_ticks,
            label=(
                f"{hit_label} | LEG {visual.leg_number} | "
                f"Net PnL {trade.net_pnl:.2f}{r_text} | "
                f"OPEN {self._format_time(visual.entry_time_ns)} | "
                f"CLOSE {self._format_time(trade.exit_time_ns)}"
            ),
            z_index=20,
        )
        context.chart.marker(
            f"yj.exit.{trade.trade_id}",
            trade.symbol,
            self.config.signal_timeframe,
            trade.exit_time_ns,
            ChartMarkerShape.SQUARE,
            ChartMarkerPosition.IN_BAR,
            "#089981" if trade.net_pnl > 0 else "#F23645",
            price_ticks=trade.exit_price_ticks,
            text=f"{hit_label} {trade.net_pnl:.2f}",
            z_index=31,
        )
        context.log.info(
            "yj_position_closed",
            trade_id=trade.trade_id,
            chain_id=visual.chain_id,
            trade_date=visual.trade_date.isoformat(),
            leg_number=visual.leg_number,
            exit_reason=trade.exit_reason,
            net_pnl=float(trade.net_pnl),
            r_multiple=(
                None
                if trade.realized_r_multiple is None
                else float(trade.realized_r_multiple)
            ),
        )

    def _draw_forming_box(
        self,
        context: StrategyContext,
        trade_date: date,
    ) -> None:
        day_bars = self._bars_by_date.get(trade_date, {})
        if not day_bars:
            return

        ordered = tuple(day_bars[minute] for minute in sorted(day_bars))
        high_ticks = max(bar.high_ticks for bar in ordered)
        low_ticks = min(bar.low_ticks for bar in ordered)
        if high_ticks <= low_ticks:
            return

        self._draw_box(
            context,
            BoxState(
                trade_date=trade_date,
                start_time_ns=ordered[0].open_time_ns,
                end_time_ns=ordered[-1].close_time_ns,
                high_ticks=high_ticks,
                low_ticks=low_ticks,
                bar_count=len(ordered),
            ),
            forming=True,
        )

    def _delete_box_drawings(
        self,
        context: StrategyContext,
        trade_date: date,
    ) -> None:
        drawing_key = trade_date.isoformat()
        context.chart.delete(f"yj.box.{drawing_key}")
        context.chart.delete(f"yj.box.high.{drawing_key}")
        context.chart.delete(f"yj.box.low.{drawing_key}")

    def _draw_box(
        self,
        context: StrategyContext,
        box: BoxState,
        *,
        forming: bool = False,
    ) -> None:
        drawing_key = box.trade_date.isoformat()
        context.chart.rectangle(
            f"yj.box.{drawing_key}",
            self.config.symbol,
            self.config.signal_timeframe,
            box.start_time_ns,
            box.low_ticks,
            box.end_time_ns,
            box.high_ticks,
            border_color="#2962FF",
            fill_color="#2962FF",
            fill_opacity=Decimal("0.08") if forming else Decimal("0.16"),
            border_width=1 if forming else 2,
            border_style=(
                ChartLineStyle.DASHED if forming else ChartLineStyle.SOLID
            ),
            label=(
                f"YJ TEHRAN 01:30–03:30 "
                f"{'FORMING' if forming else 'BOX'} | "
                f"{box.bar_count}/8 | High {box.high_ticks} | "
                f"Low {box.low_ticks}"
            ),
            z_index=5,
        )

        day_end_ns = self._next_midnight_ns(box.trade_date)
        context.chart.trend_line(
            f"yj.box.high.{drawing_key}",
            self.config.symbol,
            self.config.signal_timeframe,
            box.end_time_ns,
            box.high_ticks,
            day_end_ns,
            box.high_ticks,
            color="#2962FF",
            width=1,
            style=(
                ChartLineStyle.DOTTED
                if forming
                else ChartLineStyle.DASHED
            ),
            z_index=4,
        )
        context.chart.trend_line(
            f"yj.box.low.{drawing_key}",
            self.config.symbol,
            self.config.signal_timeframe,
            box.end_time_ns,
            box.low_ticks,
            day_end_ns,
            box.low_ticks,
            color="#2962FF",
            width=1,
            style=(
                ChartLineStyle.DOTTED
                if forming
                else ChartLineStyle.DASHED
            ),
            z_index=4,
        )

    def _handle_reversal_rejection(
        self,
        context: StrategyContext,
        event: EventEnvelope[dict[str, JsonValue]],
    ) -> None:
        payload = {
            key: value
            for key, value in event.payload.items()
            if key in Order.model_fields
        }
        if not payload:
            return

        order = Order.model_validate(payload)
        if order.request.tags.get("broker_generated") != "stop_and_reverse":
            return

        context.log.warning(
            "yj_reversal_rejected",
            order_id=order.order_id,
            chain_id=order.request.tags.get("chain_id", ""),
            trade_date=order.request.tags.get("trade_date", ""),
            reason=order.rejection_reason,
        )

    def _position_identity(self, position: Position) -> tuple[date, str, int]:
        tags = getattr(position, "entry_tags", {}) or {}
        raw_date = tags.get("trade_date")
        raw_chain = tags.get("chain_id") or tags.get(
            STOP_AND_REVERSE_CHAIN_ID_TAG
        )
        raw_leg = tags.get("leg", "1")

        try:
            trade_date = date.fromisoformat(raw_date) if raw_date else None
        except ValueError:
            trade_date = None

        try:
            leg_number = int(raw_leg)
        except ValueError:
            leg_number = 1

        if trade_date is None:
            event_date = self._session_datetime(position.opened_time_ns).date()
            candidate = self._latest_box_on_or_before(event_date)
            trade_date = (
                candidate.trade_date
                if candidate is not None
                else event_date
            )

        chain_id = raw_chain or self._chain_ids_by_date.get(
            trade_date,
            f"{trade_date.isoformat()}-unknown",
        )
        return trade_date, chain_id, 2 if leg_number == 2 else 1

    def _latest_box_on_or_before(self, value: date) -> BoxState | None:
        candidates = [
            box for day, box in self._boxes.items() if day <= value
        ]
        return (
            max(candidates, key=lambda box: box.trade_date)
            if candidates
            else None
        )

    def _redraw_audit_box(
        self,
        context: StrategyContext,
        trade_date: date,
    ) -> None:
        if not self.config.draw_box:
            return

        box = self._boxes.get(trade_date)
        if box is not None:
            self._draw_box(context, box)

    def _prune_state(self, current_date: date) -> None:
        cutoff = current_date - timedelta(days=7)
        self._bars_by_date = {
            day: bars
            for day, bars in self._bars_by_date.items()
            if day >= cutoff
        }

    @staticmethod
    def _exit_label(reason: str) -> str:
        if reason.startswith("take_profit"):
            return "TP HIT"
        if reason.startswith("stop_loss"):
            return "SL HIT"
        if reason == "end_of_data":
            return "END OF DATA"
        if reason == "stop_out":
            return "LIQUIDATED"
        return reason.replace("_", " ").upper()

    def _session_datetime(self, value_ns: int) -> datetime:
        utc_value = datetime.fromtimestamp(
            value_ns / NANOSECONDS_PER_SECOND,
            tz=UTC,
        )
        return utc_value.astimezone(self._session_zone)

    def _next_midnight_ns(self, value: date) -> int:
        next_day = datetime.combine(
            value + timedelta(days=1),
            time.min,
            tzinfo=self._session_zone,
        )
        return int(
            next_day.astimezone(UTC).timestamp() * NANOSECONDS_PER_SECOND
        )

    def _format_time(self, value_ns: int) -> str:
        return self._session_datetime(value_ns).strftime(
            "%Y-%m-%d %H:%M %Z"
        )
