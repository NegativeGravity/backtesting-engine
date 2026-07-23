from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import ClassVar, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vex_contracts.enums import (
    ChartLineStyle,
    ChartMarkerPosition,
    ChartMarkerShape,
    EventType,
    PositionSide,
    Side,
)
from vex_contracts.events import EventEnvelope
from vex_contracts.json_types import JsonValue
from vex_contracts.market import Bar
from vex_contracts.positions import Position, Trade
from vex_contracts.timeframes import Timeframe
from vex_strategy.base import Strategy
from vex_strategy.context import StrategyContext

from .core import (
    Candle,
    ClockAlignedM2Delta,
    Direction,
    RiskGovernor,
    SessionState,
    SetupKind,
    Signal,
    SignalEngine,
    resolve_reverse_chain_id,
    strategy_accounting_r,
)

STOP_AND_REVERSE_ENABLED_TAG = "vex.stop_and_reverse.enabled"
STOP_AND_REVERSE_STOP_TICKS_TAG = "vex.stop_and_reverse.stop_ticks"
STOP_AND_REVERSE_REWARD_RISK_TAG = "vex.stop_and_reverse.reward_risk"
STOP_AND_REVERSE_CHAIN_ID_TAG = "vex.stop_and_reverse.chain_id"
STOP_AND_REVERSE_ACCOUNT_BASIS_TAG = "vex.stop_and_reverse.account_basis"
EXECUTION_RISK_REWARD_ENABLED_TAG = "vex.execution_risk_reward.enabled"
EXECUTION_REWARD_RISK_TAG = "vex.execution_risk_reward.ratio"
EXECUTION_ACCOUNT_BASIS_TAG = "vex.execution_risk_reward.account_basis"
INTRABAR_ENTRY_TARGET_ALLOWED_TAG = "vex.intrabar_entry.target_allowed"

NANOSECONDS_PER_SECOND = 1_000_000_000


@dataclass(slots=True)
class VisualTrade:
    signal: Signal
    trade_date: date
    chain_id: str
    leg: int


class LsVolumeDeltaParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = "US30"
    signal_timeframe: Timeframe = Timeframe.M15
    delta_source_timeframe: Timeframe = Timeframe.M1
    session_timezone: str = "Asia/Tehran"
    session_start_minute: int = Field(default=720, ge=0, le=1439)
    session_end_minute: int = Field(default=1170, ge=1, le=1440)
    primary_reward_risk: Decimal = Field(default=Decimal("2"), gt=0)
    cover_reward_risk: Decimal = Field(default=Decimal("1"), gt=0)
    minimum_m2_bars: int = Field(default=7, ge=1, le=8)
    maximum_structure_age: int = Field(default=3, ge=1, le=20)
    maximum_positions_per_day: int = Field(default=5, ge=1, le=50)
    maximum_primary_take_profits_per_day: int = Field(default=2, ge=1, le=20)
    daily_loss_limit_r: Decimal = Decimal("-4")
    monthly_loss_limit_r: Decimal = Decimal("-8")
    monthly_pause_target_r: Decimal = Decimal("6")
    monthly_profit_target_r: Decimal = Decimal("8")
    pause_loss_threshold_r: Decimal = Decimal("-7")
    risk_accounting_mode: Literal["nominal", "broker_realized"] = "nominal"
    enable_cover: bool = True
    draw_session_range: bool = True
    draw_raw_confirmations: bool = False

    @model_validator(mode="after")
    def validate_strategy(self) -> LsVolumeDeltaParameters:
        if self.signal_timeframe is not Timeframe.M15:
            raise ValueError("signal_timeframe must be M15")
        if self.delta_source_timeframe is not Timeframe.M1:
            raise ValueError("delta_source_timeframe must be M1")
        if self.session_end_minute <= self.session_start_minute:
            raise ValueError("session_end_minute must follow session_start_minute")
        if self.daily_loss_limit_r >= 0 or self.monthly_loss_limit_r >= 0:
            raise ValueError("loss limits must be negative")
        if self.monthly_pause_target_r >= self.monthly_profit_target_r:
            raise ValueError("monthly pause target must be below final target")
        try:
            ZoneInfo(self.session_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("invalid session_timezone") from exc
        return self


class LsVolumeDeltaStrategy(Strategy):
    parameter_model: ClassVar[type[BaseModel]] = LsVolumeDeltaParameters

    def __init__(self, parameters: dict[str, JsonValue]) -> None:
        super().__init__(parameters)
        config = self.config
        self._zone = ZoneInfo(config.session_timezone)
        self._delta = ClockAlignedM2Delta()
        self._signals = SignalEngine(
            maximum_structure_age=config.maximum_structure_age,
            minimum_m2_bars=config.minimum_m2_bars,
        )
        self._risk = RiskGovernor(
            maximum_positions_per_day=config.maximum_positions_per_day,
            maximum_primary_take_profits_per_day=(
                config.maximum_primary_take_profits_per_day
            ),
            daily_loss_limit_r=config.daily_loss_limit_r,
            monthly_loss_limit_r=config.monthly_loss_limit_r,
            monthly_pause_target_r=config.monthly_pause_target_r,
            monthly_profit_target_r=config.monthly_profit_target_r,
            pause_loss_threshold_r=config.pause_loss_threshold_r,
        )
        self._previous_m15: Candle | None = None
        self._session: SessionState | None = None
        self._chain_sequence = 0
        self._visual_by_position: dict[str, VisualTrade] = {}
        self._signal_by_chain: dict[str, Signal] = {}

    @property
    def config(self) -> LsVolumeDeltaParameters:
        return LsVolumeDeltaParameters.model_validate(self.parameters)

    def on_start(self, context: StrategyContext) -> None:
        context.chart.declare_pane(
            "ls.main",
            "LS + 2m Volume Delta",
            overlay=True,
        )
        context.log.info(
            "ls_volume_delta_started",
            symbol=self.config.symbol,
            signal_timeframe=self.config.signal_timeframe.value,
            delta_source_timeframe=self.config.delta_source_timeframe.value,
            session_timezone=self.config.session_timezone,
            session_start_minute=self.config.session_start_minute,
            session_end_minute=self.config.session_end_minute,
            primary_reward_risk=float(self.config.primary_reward_risk),
            cover_reward_risk=float(self.config.cover_reward_risk),
        )

    def on_bar(self, context: StrategyContext, bar: Bar) -> None:
        if bar.symbol != self.config.symbol:
            return
        candle = self._candle(bar)

        if bar.timeframe is self.config.delta_source_timeframe:
            self._delta.push_m1(candle)
            self._delta.prune(
                candle.close_time_ns
                - 2 * 24 * 60 * 60 * NANOSECONDS_PER_SECOND
            )
            return

        if bar.timeframe is not self.config.signal_timeframe:
            return

        opened = self._local_datetime(candle.open_time_ns)
        trade_date = opened.date()
        minute = opened.hour * 60 + opened.minute
        in_session = (
            self.config.session_start_minute
            <= minute
            < self.config.session_end_minute
        )

        if self._session is None or self._session.trade_date != trade_date:
            self._session = SessionState(trade_date)

        if not in_session:
            self._signals.observe_without_signal(candle, self._previous_m15)
            self._previous_m15 = candle
            return

        session_high_before, session_low_before = (
            self._session.snapshot_extremes()
        )
        delta, m2_count = self._delta.delta_for(
            candle,
            minimum_bars=self.config.minimum_m2_bars,
        )

        signal = self._signals.evaluate(
            candle,
            self._previous_m15,
            volume_delta=delta,
            m2_bar_count=m2_count,
            session_high_before=session_high_before,
            session_low_before=session_low_before,
        )
        self._session.include(candle)
        self._draw_session(context)
        self._previous_m15 = candle

        if signal is None:
            self._draw_raw_confirmation(
                context,
                candle,
                delta=delta,
                m2_count=m2_count,
            )
            return

        permission = self._risk.permission(trade_date)
        if not permission.allowed:
            context.log.info(
                "ls_signal_rejected_by_risk",
                trade_date=trade_date.isoformat(),
                reason=permission.reason,
                setup_kind=signal.setup_kind.value,
                direction=signal.direction.value,
                volume_delta=signal.volume_delta,
                **self._risk.status(),
            )
            return

        if context.portfolio.positions(self.config.symbol):
            context.log.info(
                "ls_signal_rejected_position_open",
                trade_date=trade_date.isoformat(),
                setup_kind=signal.setup_kind.value,
                direction=signal.direction.value,
            )
            return

        cover_enabled = self.config.enable_cover and permission.cover_enabled
        self._submit_primary(
            context,
            signal,
            trade_date=trade_date,
            cover_enabled=cover_enabled,
        )
        self._draw_signal(context, signal, cover_enabled=cover_enabled)

    def on_order_update(
        self,
        context: StrategyContext,
        event: EventEnvelope[dict[str, JsonValue]],
    ) -> None:
        if event.event_type is EventType.POSITION_OPENED:
            self._position_opened(context, event)
            return
        if event.event_type in {
            EventType.POSITION_CLOSED,
            EventType.POSITION_LIQUIDATED,
        }:
            self._position_closed(context, event)

    def on_stop(self, context: StrategyContext, reason: str) -> None:
        context.log.info(
            "ls_volume_delta_stopped",
            reason=reason,
            **self._risk.status(),
        )

    def _submit_primary(
        self,
        context: StrategyContext,
        signal: Signal,
        *,
        trade_date: date,
        cover_enabled: bool,
    ) -> None:
        self._chain_sequence += 1
        chain_id = (
            f"ls-{trade_date.isoformat()}-{self._chain_sequence:05d}"
        )
        tags = {
            "strategy": "ls_volume_delta",
            "trade_date": trade_date.isoformat(),
            "chain_id": chain_id,
            "leg": "1",
            "setup_kind": signal.setup_kind.value,
            "volume_delta": str(signal.volume_delta),
            "m2_bar_count": str(signal.m2_bar_count),
            "signal_open_time_ns": str(signal.candle.open_time_ns),
            "signal_close_time_ns": str(signal.candle.close_time_ns),
            "signal_open_ticks": str(signal.candle.open_ticks),
            "signal_high_ticks": str(signal.candle.high_ticks),
            "signal_low_ticks": str(signal.candle.low_ticks),
            "signal_close_ticks": str(signal.candle.close_ticks),
            "hunted_structure_id": signal.hunted_structure_id or "",
            "hunted_structure_ticks": (
                ""
                if signal.hunted_structure_ticks is None
                else str(signal.hunted_structure_ticks)
            ),
            "hunted_structure_time_ns": (
                ""
                if signal.hunted_structure_time_ns is None
                else str(signal.hunted_structure_time_ns)
            ),
            "cover_enabled": "true" if cover_enabled else "false",
            EXECUTION_RISK_REWARD_ENABLED_TAG: "true",
            EXECUTION_REWARD_RISK_TAG: str(
                self.config.primary_reward_risk
            ),
            EXECUTION_ACCOUNT_BASIS_TAG: "balance",
            INTRABAR_ENTRY_TARGET_ALLOWED_TAG: "true",
        }
        if cover_enabled:
            tags.update(
                {
                    STOP_AND_REVERSE_ENABLED_TAG: "true",
                    STOP_AND_REVERSE_STOP_TICKS_TAG: str(
                        signal.cover_stop_ticks
                    ),
                    STOP_AND_REVERSE_REWARD_RISK_TAG: str(
                        self.config.cover_reward_risk
                    ),
                    STOP_AND_REVERSE_CHAIN_ID_TAG: chain_id,
                    STOP_AND_REVERSE_ACCOUNT_BASIS_TAG: "balance",
                }
            )

        side = (
            Side.BUY
            if signal.direction is Direction.LONG
            else Side.SELL
        )
        context.orders.market(
            self.config.symbol,
            side,
            volume_lots=None,
            stop_loss_ticks=signal.stop_ticks,
            take_profit_ticks=None,
            client_order_id=f"{chain_id}-primary",
            tags=tags,
        )
        self._signal_by_chain[chain_id] = signal
        context.log.info(
            "ls_primary_submitted",
            trade_date=trade_date.isoformat(),
            chain_id=chain_id,
            direction=signal.direction.value,
            setup_kind=signal.setup_kind.value,
            stop_ticks=signal.stop_ticks,
            cover_stop_ticks=signal.cover_stop_ticks,
            cover_enabled=cover_enabled,
            volume_delta=signal.volume_delta,
            m2_bar_count=signal.m2_bar_count,
            **self._risk.status(),
        )

    def _position_opened(
        self,
        context: StrategyContext,
        event: EventEnvelope[dict[str, JsonValue]],
    ) -> None:
        position = Position.model_validate(event.payload)
        if position.symbol != self.config.symbol:
            return
        raw_tags = getattr(position, "entry_tags", {}) or {}
        tags, recovered = self._normalized_entry_tags(
            raw_tags,
            event_name="POSITION_OPENED",
            object_id=position.position_id,
            event_time_ns=position.opened_time_ns,
            entry_client_order_id=getattr(
                position,
                "entry_client_order_id",
                None,
            ),
        )
        if recovered:
            context.log.warning(
                "ls_cover_metadata_recovered",
                position_id=position.position_id,
                chain_id=tags["chain_id"],
                source_keys=self._log_source_keys(raw_tags),
                source_key_count=len(raw_tags),
            )

        raw_date = tags.get("trade_date")
        try:
            trade_date = (
                date.fromisoformat(raw_date)
                if raw_date
                else self._local_datetime(position.opened_time_ns).date()
            )
        except ValueError as exc:
            raise RuntimeError(
                "LS position contains an invalid trade_date entry tag: "
                f"{raw_date!r}"
            ) from exc
        chain_id = tags.get("chain_id", position.position_id)
        leg = self._parse_leg(tags.get("leg"))
        signal = self._signal_by_chain.get(chain_id)
        if signal is None:
            signal = self._signal_from_tags(tags, position)

        opened_date = self._local_datetime(position.opened_time_ns).date()
        self._risk.position_opened(opened_date)
        visual = VisualTrade(
            signal=signal,
            trade_date=trade_date,
            chain_id=chain_id,
            leg=leg,
        )
        self._visual_by_position[position.position_id] = visual
        if leg == 2:
            context.chart.delete(
                f"ls.cover.entry.{signal.candle.open_time_ns}"
            )

        if (
            position.stop_loss_ticks is not None
            and position.take_profit_ticks is not None
        ):
            context.chart.risk_reward(
                f"ls.trade.{position.position_id}",
                position.position_id,
                position.symbol,
                self.config.signal_timeframe,
                position.side,
                position.opened_time_ns,
                position.average_entry_price_ticks,
                position.stop_loss_ticks,
                position.take_profit_ticks,
                label=(
                    f"{signal.setup_kind.value.upper()} | "
                    f"Δ {signal.volume_delta:+d} | "
                    f"{'MAIN 2R' if leg == 1 else 'COVER 1R'}"
                ),
                z_index=20,
            )

        context.chart.marker(
            f"ls.entry.{position.position_id}",
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
            "#12B886" if position.side is PositionSide.LONG else "#FA5252",
            price_ticks=position.average_entry_price_ticks,
            text=f"{'M' if leg == 1 else 'C'} · Δ{signal.volume_delta:+d}",
            z_index=31,
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
        raw_tags = getattr(trade, "entry_tags", {}) or {}
        tags, recovered = self._normalized_entry_tags(
            raw_tags,
            event_name="POSITION_CLOSED",
            object_id=trade.trade_id,
            event_time_ns=trade.entry_time_ns,
            entry_client_order_id=getattr(
                trade,
                "entry_client_order_id",
                None,
            ),
        )
        if recovered:
            context.log.warning(
                "ls_cover_trade_metadata_recovered",
                trade_id=trade.trade_id,
                chain_id=tags["chain_id"],
                source_keys=self._log_source_keys(raw_tags),
                source_key_count=len(raw_tags),
            )

        leg = self._parse_leg(tags.get("leg"))
        close_date = self._local_datetime(trade.exit_time_ns).date()
        take_profit = trade.exit_reason.startswith("take_profit")
        realized_r = strategy_accounting_r(
            exit_reason=trade.exit_reason,
            leg=leg,
            broker_realized_r=trade.realized_r_multiple,
            primary_reward_risk=self.config.primary_reward_risk,
            cover_reward_risk=self.config.cover_reward_risk,
            mode=self.config.risk_accounting_mode,
        )
        self._risk.trade_closed(
            close_date,
            realized_r=realized_r,
            leg=leg,
            take_profit=take_profit,
        )
        visual = self._visual_by_position.pop(trade.position_id, None)
        chain_id = tags.get("chain_id", "")
        cover_enabled = tags.get("cover_enabled") == "true"
        chain_completed = (
            leg == 2
            or take_profit
            or (leg == 1 and not cover_enabled)
            or trade.exit_reason == "stop_out"
            or trade.exit_reason == "end_of_data"
        )
        if chain_completed and chain_id:
            self._signal_by_chain.pop(chain_id, None)
        if leg == 1 and take_profit and visual is not None:
            context.chart.delete(
                f"ls.cover.entry.{visual.signal.candle.open_time_ns}"
            )

        context.chart.marker(
            f"ls.exit.{trade.trade_id}",
            trade.symbol,
            self.config.signal_timeframe,
            trade.exit_time_ns,
            ChartMarkerShape.SQUARE,
            ChartMarkerPosition.IN_BAR,
            "#12B886" if trade.net_pnl > 0 else "#FA5252",
            price_ticks=trade.exit_price_ticks,
            text=(
                f"{'TP' if take_profit else 'SL'} "
                f"{realized_r:+.2f}R"
            ),
            z_index=32,
        )
        context.log.info(
            "ls_trade_closed",
            trade_id=trade.trade_id,
            chain_id=chain_id,
            leg=leg,
            exit_reason=trade.exit_reason,
            realized_r=float(realized_r),
            trade_date=(
                visual.trade_date.isoformat()
                if visual is not None
                else tags.get("trade_date", "")
            ),
            **self._risk.status(),
        )

    def _draw_signal(
        self,
        context: StrategyContext,
        signal: Signal,
        *,
        cover_enabled: bool,
    ) -> None:
        drawing_id = f"ls.signal.{signal.candle.open_time_ns}"
        long_signal = signal.direction is Direction.LONG
        context.chart.marker(
            drawing_id,
            self.config.symbol,
            self.config.signal_timeframe,
            signal.candle.open_time_ns,
            (
                ChartMarkerShape.ARROW_UP
                if long_signal
                else ChartMarkerShape.ARROW_DOWN
            ),
            (
                ChartMarkerPosition.BELOW_BAR
                if long_signal
                else ChartMarkerPosition.ABOVE_BAR
            ),
            "#20C997" if long_signal else "#FF6B6B",
            price_ticks=(
                signal.candle.low_ticks
                if long_signal
                else signal.candle.high_ticks
            ),
            text=(
                f"{self._setup_label(signal.setup_kind)} "
                f"Δ{signal.volume_delta:+d}"
            ),
            z_index=15,
        )
        if (
            signal.hunted_structure_ticks is not None
            and signal.hunted_structure_id is not None
        ):
            context.chart.trend_line(
                f"ls.hunt.{signal.candle.open_time_ns}",
                self.config.symbol,
                self.config.signal_timeframe,
                signal.hunted_structure_time_ns
                or signal.candle.open_time_ns,
                signal.hunted_structure_ticks,
                signal.candle.close_time_ns,
                signal.hunted_structure_ticks,
                color="#868E96",
                width=1,
                style=ChartLineStyle.DASHED,
                z_index=7,
            )
        if cover_enabled:
            context.chart.trend_line(
                f"ls.cover.entry.{signal.candle.open_time_ns}",
                self.config.symbol,
                self.config.signal_timeframe,
                signal.candle.close_time_ns,
                signal.stop_ticks,
                self._session_end_ns(
                    self._local_datetime(signal.candle.open_time_ns).date()
                ),
                signal.stop_ticks,
                color="#FCC419",
                width=1,
                style=ChartLineStyle.DOTTED,
                z_index=9,
            )

    def _draw_raw_confirmation(
        self,
        context: StrategyContext,
        candle: Candle,
        *,
        delta: int,
        m2_count: int,
    ) -> None:
        if not self.config.draw_raw_confirmations:
            return
        if m2_count < self.config.minimum_m2_bars:
            return
        long_confirmed = candle.long_ls and delta < 0
        short_confirmed = candle.short_ls and delta > 0
        if long_confirmed == short_confirmed:
            return
        context.chart.marker(
            f"ls.raw.{candle.open_time_ns}",
            self.config.symbol,
            self.config.signal_timeframe,
            candle.open_time_ns,
            ChartMarkerShape.SQUARE,
            (
                ChartMarkerPosition.BELOW_BAR
                if long_confirmed
                else ChartMarkerPosition.ABOVE_BAR
            ),
            "#74C0FC",
            price_ticks=(
                candle.low_ticks if long_confirmed else candle.high_ticks
            ),
            text=f"LS Δ{delta:+d}",
            z_index=6,
        )

    def _draw_session(self, context: StrategyContext) -> None:
        if not self.config.draw_session_range or self._session is None:
            return
        if (
            self._session.first_time_ns is None
            or self._session.last_time_ns is None
            or self._session.high_ticks is None
            or self._session.low_ticks is None
        ):
            return
        context.chart.rectangle(
            f"ls.session.{self._session.trade_date.isoformat()}",
            self.config.symbol,
            self.config.signal_timeframe,
            self._session.first_time_ns,
            self._session.low_ticks,
            self._session.last_time_ns,
            self._session.high_ticks,
            border_color="#5C7CFA",
            fill_color="#5C7CFA",
            fill_opacity=Decimal("0.025"),
            border_width=1,
            border_style=ChartLineStyle.DOTTED,
            label=self._session_label(),
            z_index=2,
        )

    def _signal_from_tags(
        self,
        tags: dict[str, str],
        position: Position,
    ) -> Signal:
        direction = (
            Direction.LONG
            if position.side is PositionSide.LONG
            else Direction.SHORT
        )
        candle = Candle(
            open_time_ns=int(
                tags.get("signal_open_time_ns", position.opened_time_ns)
            ),
            close_time_ns=int(
                tags.get("signal_close_time_ns", position.opened_time_ns + 1)
            ),
            open_ticks=int(
                tags.get(
                    "signal_open_ticks",
                    position.average_entry_price_ticks,
                )
            ),
            high_ticks=int(
                tags.get(
                    "signal_high_ticks",
                    position.average_entry_price_ticks,
                )
            ),
            low_ticks=int(
                tags.get(
                    "signal_low_ticks",
                    position.average_entry_price_ticks,
                )
            ),
            close_ticks=int(
                tags.get(
                    "signal_close_ticks",
                    position.average_entry_price_ticks,
                )
            ),
        )
        return Signal(
            direction=direction,
            setup_kind=SetupKind(
                tags.get("setup_kind", SetupKind.LS.value)
            ),
            candle=candle,
            volume_delta=int(tags.get("volume_delta", "0")),
            m2_bar_count=int(tags.get("m2_bar_count", "0")),
            stop_ticks=(
                position.stop_loss_ticks
                if position.stop_loss_ticks is not None
                else (
                    candle.low_ticks
                    if direction is Direction.LONG
                    else candle.high_ticks
                )
            ),
            cover_stop_ticks=(
                candle.body_high_ticks
                if direction is Direction.LONG
                else candle.body_low_ticks
            ),
            hunted_structure_id=tags.get("hunted_structure_id") or None,
            hunted_structure_ticks=(
                int(tags["hunted_structure_ticks"])
                if tags.get("hunted_structure_ticks")
                else None
            ),
            hunted_structure_time_ns=(
                int(tags["hunted_structure_time_ns"])
                if tags.get("hunted_structure_time_ns")
                else None
            ),
        )

    def _normalized_entry_tags(
        self,
        tags: dict[str, str],
        *,
        event_name: str,
        object_id: str,
        event_time_ns: int,
        entry_client_order_id: str | None,
    ) -> tuple[dict[str, str], bool]:
        normalized = dict(tags)
        if normalized.get("strategy") == "ls_volume_delta":
            self._validate_entry_tags(
                normalized,
                event_name=event_name,
                object_id=object_id,
            )
            return normalized, False

        broker_generated = normalized.get("broker_generated")
        leg = self._parse_leg(normalized.get("leg"))
        if broker_generated != "stop_and_reverse" or leg != 2:
            self._raise_metadata_error(
                normalized,
                event_name=event_name,
                object_id=object_id,
            )

        chain_id = resolve_reverse_chain_id(
            normalized,
            self._signal_by_chain,
            client_order_id=entry_client_order_id,
            broker_chain_tag=STOP_AND_REVERSE_CHAIN_ID_TAG,
        )
        if not chain_id or chain_id not in self._signal_by_chain:
            raise RuntimeError(
                "LS cover metadata recovery failed for "
                f"{event_name} {object_id}: "
                f"chain_id={chain_id!r}, "
                f"active_chains={sorted(self._signal_by_chain)}, "
                f"source_keys={sorted(normalized)}"
            )

        signal = self._signal_by_chain[chain_id]
        trade_date = self._chain_trade_date(
            chain_id,
            fallback_time_ns=event_time_ns,
        )
        normalized.update(
            {
                "strategy": "ls_volume_delta",
                "trade_date": trade_date.isoformat(),
                "chain_id": chain_id,
                "leg": "2",
                "cover_enabled": "false",
                **self._signal_metadata_tags(signal),
            }
        )
        self._validate_entry_tags(
            normalized,
            event_name=event_name,
            object_id=object_id,
        )
        return normalized, True

    @staticmethod
    def _log_source_keys(tags: dict[str, str]) -> str:
        return ",".join(sorted(str(key) for key in tags))

    @staticmethod
    def _signal_metadata_tags(signal: Signal) -> dict[str, str]:
        return {
            "setup_kind": signal.setup_kind.value,
            "volume_delta": str(signal.volume_delta),
            "m2_bar_count": str(signal.m2_bar_count),
            "signal_open_time_ns": str(signal.candle.open_time_ns),
            "signal_close_time_ns": str(signal.candle.close_time_ns),
            "signal_open_ticks": str(signal.candle.open_ticks),
            "signal_high_ticks": str(signal.candle.high_ticks),
            "signal_low_ticks": str(signal.candle.low_ticks),
            "signal_close_ticks": str(signal.candle.close_ticks),
            "hunted_structure_id": signal.hunted_structure_id or "",
            "hunted_structure_ticks": (
                ""
                if signal.hunted_structure_ticks is None
                else str(signal.hunted_structure_ticks)
            ),
            "hunted_structure_time_ns": (
                ""
                if signal.hunted_structure_time_ns is None
                else str(signal.hunted_structure_time_ns)
            ),
        }

    def _chain_trade_date(
        self,
        chain_id: str,
        *,
        fallback_time_ns: int,
    ) -> date:
        if chain_id.startswith("ls-") and len(chain_id) >= 13:
            try:
                return date.fromisoformat(chain_id[3:13])
            except ValueError:
                pass
        return self._local_datetime(fallback_time_ns).date()

    @staticmethod
    def _validate_entry_tags(
        tags: dict[str, str],
        *,
        event_name: str,
        object_id: str,
    ) -> None:
        required = {"strategy", "trade_date", "chain_id", "leg"}
        missing = sorted(key for key in required if not tags.get(key))
        if tags.get("strategy") != "ls_volume_delta" or missing:
            LsVolumeDeltaStrategy._raise_metadata_error(
                tags,
                event_name=event_name,
                object_id=object_id,
            )

    @staticmethod
    def _raise_metadata_error(
        tags: dict[str, str],
        *,
        event_name: str,
        object_id: str,
    ) -> None:
        required = {"strategy", "trade_date", "chain_id", "leg"}
        missing = sorted(key for key in required if not tags.get(key))
        raise RuntimeError(
            "LS broker metadata propagation failed for "
            f"{event_name} {object_id}: "
            f"strategy={tags.get('strategy')!r}, missing={missing}, "
            f"source_keys={sorted(tags)}"
        )

    def _candle(self, bar: Bar) -> Candle:
        return Candle(
            open_time_ns=bar.open_time_ns,
            close_time_ns=bar.close_time_ns,
            open_ticks=bar.open_ticks,
            high_ticks=bar.high_ticks,
            low_ticks=bar.low_ticks,
            close_ticks=bar.close_ticks,
            volume=self._bar_volume(bar),
        )

    @staticmethod
    def _bar_volume(bar: Bar) -> int:
        for name in ("tick_volume", "volume", "real_volume"):
            value = getattr(bar, name, 0)
            if value:
                return int(value)
        return 0

    def _local_datetime(self, value_ns: int) -> datetime:
        return datetime.fromtimestamp(
            value_ns / NANOSECONDS_PER_SECOND,
            tz=UTC,
        ).astimezone(self._zone)

    def _session_end_ns(self, trade_date: date) -> int:
        if self.config.session_end_minute == 1440:
            end_local = datetime.combine(
                trade_date + timedelta(days=1),
                time.min,
                tzinfo=self._zone,
            )
        else:
            hour, minute = divmod(self.config.session_end_minute, 60)
            end_local = datetime.combine(
                trade_date,
                time(hour=hour, minute=minute),
                tzinfo=self._zone,
            )
        return int(
            end_local.astimezone(UTC).timestamp() * NANOSECONDS_PER_SECOND
        )

    def _session_label(self) -> str:
        start_hour, start_minute = divmod(
            self.config.session_start_minute,
            60,
        )
        end_hour, end_minute = divmod(
            self.config.session_end_minute,
            60,
        )
        return (
            f"LS SESSION {start_hour:02d}:{start_minute:02d}-"
            f"{end_hour:02d}:{end_minute:02d}"
        )

    @staticmethod
    def _parse_leg(raw: str | None) -> int:
        try:
            return 2 if int(raw or "1") == 2 else 1
        except ValueError:
            return 1

    @staticmethod
    def _setup_label(kind: SetupKind) -> str:
        if kind is SetupKind.LS_ENGULF:
            return "LS+E"
        if kind is SetupKind.ENGULF:
            return "E"
        return "LS"
