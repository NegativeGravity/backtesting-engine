from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

NANOSECONDS_PER_MINUTE = 60 * 1_000_000_000


def resolve_reverse_chain_id(
    tags: dict[str, str],
    known_chain_ids: Iterable[str],
    *,
    client_order_id: str | None = None,
    broker_chain_tag: str = "vex.stop_and_reverse.chain_id",
) -> str | None:
    direct = tags.get("chain_id") or tags.get(broker_chain_tag)
    if direct:
        return direct

    known = tuple(dict.fromkeys(known_chain_ids))
    if client_order_id:
        matches = [
            chain_id
            for chain_id in known
            if chain_id and chain_id in client_order_id
        ]
        if len(matches) == 1:
            return matches[0]

    if len(known) == 1:
        return known[0]
    return None


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"


class SetupKind(StrEnum):
    LS = "ls"
    ENGULF = "engulf"
    LS_ENGULF = "ls_engulf"


class StructureKind(StrEnum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class Candle:
    open_time_ns: int
    close_time_ns: int
    open_ticks: int
    high_ticks: int
    low_ticks: int
    close_ticks: int
    volume: int = 0

    def __post_init__(self) -> None:
        if self.close_time_ns <= self.open_time_ns:
            raise ValueError("close_time_ns must be after open_time_ns")
        if self.high_ticks < max(self.open_ticks, self.close_ticks):
            raise ValueError("high_ticks is below candle body")
        if self.low_ticks > min(self.open_ticks, self.close_ticks):
            raise ValueError("low_ticks is above candle body")
        if self.volume < 0:
            raise ValueError("volume must be non-negative")

    @property
    def body_ticks(self) -> int:
        return abs(self.close_ticks - self.open_ticks)

    @property
    def body_high_ticks(self) -> int:
        return max(self.open_ticks, self.close_ticks)

    @property
    def body_low_ticks(self) -> int:
        return min(self.open_ticks, self.close_ticks)

    @property
    def upper_shadow_ticks(self) -> int:
        return self.high_ticks - self.body_high_ticks

    @property
    def lower_shadow_ticks(self) -> int:
        return self.body_low_ticks - self.low_ticks

    @property
    def bullish(self) -> bool:
        return self.close_ticks > self.open_ticks

    @property
    def bearish(self) -> bool:
        return self.close_ticks < self.open_ticks

    @property
    def doji(self) -> bool:
        return self.close_ticks == self.open_ticks

    @property
    def long_ls(self) -> bool:
        body = self.body_ticks
        lower = self.lower_shadow_ticks
        upper = self.upper_shadow_ticks
        return lower > body and lower > upper and upper < 7 * body

    @property
    def short_ls(self) -> bool:
        body = self.body_ticks
        lower = self.lower_shadow_ticks
        upper = self.upper_shadow_ticks
        return upper > body and upper > lower and lower < 7 * body


@dataclass(frozen=True, slots=True)
class M2VolumeBar:
    open_time_ns: int
    close_time_ns: int
    open_ticks: int
    high_ticks: int
    low_ticks: int
    close_ticks: int
    volume: int
    direction: int
    signed_volume: int


@dataclass(slots=True)
class ClockAlignedM2Delta:
    bucket_ns: int = 2 * NANOSECONDS_PER_MINUTE
    _pending: dict[int, list[Candle]] = field(default_factory=dict)
    _completed: list[M2VolumeBar] = field(default_factory=list)
    _previous_close_ticks: int | None = None
    _previous_direction: int = 1

    def push_m1(self, candle: Candle) -> M2VolumeBar | None:
        bucket_start = candle.open_time_ns - candle.open_time_ns % self.bucket_ns
        bucket_end = bucket_start + self.bucket_ns
        bucket = self._pending.setdefault(bucket_start, [])
        if any(item.open_time_ns == candle.open_time_ns for item in bucket):
            return None
        bucket.append(candle)
        bucket.sort(key=lambda item: item.open_time_ns)
        if candle.close_time_ns < bucket_end:
            return None

        selected = [
            item
            for item in bucket
            if item.open_time_ns >= bucket_start
            and item.close_time_ns <= bucket_end
        ]
        self._pending.pop(bucket_start, None)
        if not selected:
            return None
        if selected[0].open_time_ns != bucket_start:
            return None
        if selected[-1].close_time_ns != bucket_end:
            return None

        aggregate = Candle(
            open_time_ns=bucket_start,
            close_time_ns=bucket_end,
            open_ticks=selected[0].open_ticks,
            high_ticks=max(item.high_ticks for item in selected),
            low_ticks=min(item.low_ticks for item in selected),
            close_ticks=selected[-1].close_ticks,
            volume=sum(item.volume for item in selected),
        )
        direction = self._classify(aggregate)
        result = M2VolumeBar(
            open_time_ns=aggregate.open_time_ns,
            close_time_ns=aggregate.close_time_ns,
            open_ticks=aggregate.open_ticks,
            high_ticks=aggregate.high_ticks,
            low_ticks=aggregate.low_ticks,
            close_ticks=aggregate.close_ticks,
            volume=aggregate.volume,
            direction=direction,
            signed_volume=direction * aggregate.volume,
        )
        self._completed.append(result)
        self._previous_close_ticks = aggregate.close_ticks
        self._previous_direction = direction
        return result

    def delta_for(
        self,
        parent: Candle,
        *,
        minimum_bars: int = 7,
    ) -> tuple[int, int]:
        bars = [
            item
            for item in self._completed
            if item.open_time_ns >= parent.open_time_ns
            and item.close_time_ns <= parent.close_time_ns
        ]
        if len(bars) < minimum_bars:
            return 0, len(bars)
        return sum(item.signed_volume for item in bars), len(bars)

    def prune(self, before_time_ns: int) -> None:
        self._completed = [
            item
            for item in self._completed
            if item.close_time_ns >= before_time_ns
        ]
        self._pending = {
            key: value
            for key, value in self._pending.items()
            if key + self.bucket_ns >= before_time_ns
        }

    def _classify(self, candle: Candle) -> int:
        if candle.close_ticks > candle.open_ticks:
            return 1
        if candle.close_ticks < candle.open_ticks:
            return -1
        if self._previous_close_ticks is None:
            return self._previous_direction
        if candle.close_ticks > self._previous_close_ticks:
            return 1
        if candle.close_ticks < self._previous_close_ticks:
            return -1
        return self._previous_direction


@dataclass(slots=True)
class StructureLevel:
    structure_id: str
    kind: StructureKind
    formed_index: int
    formed_time_ns: int
    wick_ticks: int
    body_break_ticks: int
    intervening_extreme_ticks: int
    valid: bool = True
    invalidated_time_ns: int | None = None

    def strict_hunt(self, candle: Candle) -> bool:
        if not self.valid:
            return False
        if self.kind is StructureKind.HIGH:
            return (
                candle.high_ticks > self.wick_ticks
                and candle.high_ticks > self.intervening_extreme_ticks
            )
        return (
            candle.low_ticks < self.wick_ticks
            and candle.low_ticks < self.intervening_extreme_ticks
        )

    def invalidated_by_close(self, candle: Candle) -> bool:
        if self.kind is StructureKind.HIGH:
            return candle.close_ticks > self.body_break_ticks
        return candle.close_ticks < self.body_break_ticks

    def absorb_intervening(self, candle: Candle) -> None:
        if self.kind is StructureKind.HIGH:
            self.intervening_extreme_ticks = max(
                self.intervening_extreme_ticks,
                candle.high_ticks,
            )
        else:
            self.intervening_extreme_ticks = min(
                self.intervening_extreme_ticks,
                candle.low_ticks,
            )


@dataclass(frozen=True, slots=True)
class Signal:
    direction: Direction
    setup_kind: SetupKind
    candle: Candle
    volume_delta: int
    m2_bar_count: int
    stop_ticks: int
    cover_stop_ticks: int
    hunted_structure_id: str | None = None
    hunted_structure_ticks: int | None = None
    hunted_structure_time_ns: int | None = None

    @property
    def primary_risk_ticks(self) -> int:
        return (
            self.candle.close_ticks - self.stop_ticks
            if self.direction is Direction.LONG
            else self.stop_ticks - self.candle.close_ticks
        )


@dataclass(slots=True)
class SessionState:
    trade_date: date
    high_ticks: int | None = None
    low_ticks: int | None = None
    first_time_ns: int | None = None
    last_time_ns: int | None = None

    def snapshot_extremes(self) -> tuple[int | None, int | None]:
        return self.high_ticks, self.low_ticks

    def include(self, candle: Candle) -> None:
        self.high_ticks = (
            candle.high_ticks
            if self.high_ticks is None
            else max(self.high_ticks, candle.high_ticks)
        )
        self.low_ticks = (
            candle.low_ticks
            if self.low_ticks is None
            else min(self.low_ticks, candle.low_ticks)
        )
        self.first_time_ns = (
            candle.open_time_ns
            if self.first_time_ns is None
            else min(self.first_time_ns, candle.open_time_ns)
        )
        self.last_time_ns = (
            candle.close_time_ns
            if self.last_time_ns is None
            else max(self.last_time_ns, candle.close_time_ns)
        )


@dataclass(slots=True)
class SignalEngine:
    maximum_structure_age: int = 3
    minimum_m2_bars: int = 7
    bars: list[Candle] = field(default_factory=list)
    highs: list[StructureLevel] = field(default_factory=list)
    lows: list[StructureLevel] = field(default_factory=list)
    _sequence: int = 0

    def evaluate(
        self,
        candle: Candle,
        previous: Candle | None,
        *,
        volume_delta: int,
        m2_bar_count: int,
        session_high_before: int | None,
        session_low_before: int | None,
    ) -> Signal | None:
        index = len(self.bars)
        delta_available = m2_bar_count >= self.minimum_m2_bars
        long_delta = delta_available and volume_delta < 0
        short_delta = delta_available and volume_delta > 0

        long_level = self._qualifying_level(
            self._active(self.lows),
            candle,
        )
        short_level = self._qualifying_level(
            self._active(self.highs),
            candle,
        )

        long_ls_setup = candle.long_ls and long_delta and long_level is not None
        short_ls_setup = candle.short_ls and short_delta and short_level is not None

        long_engulf = (
            previous is not None
            and previous.bearish
            and candle.bullish
            and long_delta
            and session_low_before is not None
            and candle.low_ticks < session_low_before
            and candle.low_ticks < previous.body_low_ticks
        )
        short_engulf = (
            previous is not None
            and previous.bullish
            and candle.bearish
            and short_delta
            and session_high_before is not None
            and candle.high_ticks > session_high_before
            and candle.high_ticks > previous.body_high_ticks
        )

        long_setup = long_ls_setup or long_engulf
        short_setup = short_ls_setup or short_engulf
        signal: Signal | None = None

        if long_setup != short_setup:
            if long_setup:
                signal = Signal(
                    direction=Direction.LONG,
                    setup_kind=self._setup_kind(long_ls_setup, long_engulf),
                    candle=candle,
                    volume_delta=volume_delta,
                    m2_bar_count=m2_bar_count,
                    stop_ticks=candle.low_ticks,
                    cover_stop_ticks=candle.body_high_ticks,
                    hunted_structure_id=(
                        long_level.structure_id if long_ls_setup else None
                    ),
                    hunted_structure_ticks=(
                        long_level.wick_ticks if long_ls_setup else None
                    ),
                    hunted_structure_time_ns=(
                        long_level.formed_time_ns if long_ls_setup else None
                    ),
                )
            else:
                signal = Signal(
                    direction=Direction.SHORT,
                    setup_kind=self._setup_kind(short_ls_setup, short_engulf),
                    candle=candle,
                    volume_delta=volume_delta,
                    m2_bar_count=m2_bar_count,
                    stop_ticks=candle.high_ticks,
                    cover_stop_ticks=candle.body_low_ticks,
                    hunted_structure_id=(
                        short_level.structure_id if short_ls_setup else None
                    ),
                    hunted_structure_ticks=(
                        short_level.wick_ticks if short_ls_setup else None
                    ),
                    hunted_structure_time_ns=(
                        short_level.formed_time_ns if short_ls_setup else None
                    ),
                )

        self._invalidate_after_signal(candle)
        self._absorb_after_signal(candle)
        self._detect_new_structure(previous, candle, index)
        self.bars.append(candle)
        return signal

    def observe_without_signal(
        self,
        candle: Candle,
        previous: Candle | None,
    ) -> None:
        index = len(self.bars)
        self._invalidate_after_signal(candle)
        self._absorb_after_signal(candle)
        self._detect_new_structure(previous, candle, index)
        self.bars.append(candle)

    def _active(
        self,
        levels: Iterable[StructureLevel],
    ) -> list[StructureLevel]:
        recent = list(levels)[-self.maximum_structure_age :]
        return [item for item in recent if item.valid]

    @staticmethod
    def _qualifying_level(
        levels: Iterable[StructureLevel],
        candle: Candle,
    ) -> StructureLevel | None:
        for level in reversed(tuple(levels)):
            if level.strict_hunt(candle):
                return level
        return None

    @staticmethod
    def _setup_kind(ls_setup: bool, engulf_setup: bool) -> SetupKind:
        if ls_setup and engulf_setup:
            return SetupKind.LS_ENGULF
        if ls_setup:
            return SetupKind.LS
        return SetupKind.ENGULF

    def _invalidate_after_signal(self, candle: Candle) -> None:
        for level in (*self.highs, *self.lows):
            if level.valid and level.invalidated_by_close(candle):
                level.valid = False
                level.invalidated_time_ns = candle.close_time_ns

    def _absorb_after_signal(self, candle: Candle) -> None:
        for level in (*self.highs, *self.lows):
            if level.valid:
                level.absorb_intervening(candle)

    def _detect_new_structure(
        self,
        previous: Candle | None,
        candle: Candle,
        index: int,
    ) -> None:
        if previous is None:
            return
        if previous.bullish and candle.bearish:
            self._sequence += 1
            self.highs.append(
                StructureLevel(
                    structure_id=f"H-{self._sequence:06d}",
                    kind=StructureKind.HIGH,
                    formed_index=index,
                    formed_time_ns=candle.close_time_ns,
                    wick_ticks=max(previous.high_ticks, candle.high_ticks),
                    body_break_ticks=max(
                        previous.body_high_ticks,
                        candle.body_high_ticks,
                    ),
                    intervening_extreme_ticks=max(
                        previous.high_ticks,
                        candle.high_ticks,
                    ),
                )
            )
        if previous.bearish and candle.bullish:
            self._sequence += 1
            self.lows.append(
                StructureLevel(
                    structure_id=f"L-{self._sequence:06d}",
                    kind=StructureKind.LOW,
                    formed_index=index,
                    formed_time_ns=candle.close_time_ns,
                    wick_ticks=min(previous.low_ticks, candle.low_ticks),
                    body_break_ticks=min(
                        previous.body_low_ticks,
                        candle.body_low_ticks,
                    ),
                    intervening_extreme_ticks=min(
                        previous.low_ticks,
                        candle.low_ticks,
                    ),
                )
            )


@dataclass(slots=True)
class DayRiskState:
    trade_date: date
    realized_r: Decimal = Decimal("0")
    opened_positions: int = 0
    primary_take_profits: int = 0
    halted: bool = False


@dataclass(slots=True)
class MonthRiskState:
    year: int
    month: int
    realized_r: Decimal = Decimal("0")
    paused_until_day_15: bool = False
    halted: bool = False


@dataclass(frozen=True, slots=True)
class EntryPermission:
    allowed: bool
    cover_enabled: bool
    reason: str


@dataclass(slots=True)
class RiskGovernor:
    maximum_positions_per_day: int = 5
    maximum_primary_take_profits_per_day: int = 2
    daily_loss_limit_r: Decimal = Decimal("-4")
    monthly_loss_limit_r: Decimal = Decimal("-8")
    monthly_pause_target_r: Decimal = Decimal("6")
    monthly_profit_target_r: Decimal = Decimal("8")
    pause_loss_threshold_r: Decimal = Decimal("-7")
    day: DayRiskState | None = None
    month: MonthRiskState | None = None
    _paused_loss_date: date | None = None

    def roll(self, trade_date: date) -> None:
        if (
            self.month is None
            or (self.month.year, self.month.month)
            != (trade_date.year, trade_date.month)
        ):
            self.month = MonthRiskState(trade_date.year, trade_date.month)
            self._paused_loss_date = None
        if self.day is None or self.day.trade_date != trade_date:
            self.day = DayRiskState(trade_date)
            if self._paused_loss_date != trade_date:
                self._paused_loss_date = None
        if self.month is not None and trade_date.day >= 15:
            self.month.paused_until_day_15 = False

    def permission(self, trade_date: date) -> EntryPermission:
        self.roll(trade_date)
        assert self.day is not None
        assert self.month is not None

        if self.day.halted:
            return EntryPermission(False, False, "daily_halt")
        if self.month.halted:
            return EntryPermission(False, False, "monthly_halt")
        if self._paused_loss_date == trade_date:
            return EntryPermission(False, False, "monthly_minus_seven_day_pause")
        if (
            trade_date.day < 15
            and self.month.realized_r >= self.monthly_pause_target_r
        ):
            self.month.paused_until_day_15 = True
            return EntryPermission(False, False, "monthly_plus_six_pause")
        if self.month.realized_r >= self.monthly_profit_target_r:
            self.month.halted = True
            return EntryPermission(False, False, "monthly_profit_target")
        if self.month.realized_r <= self.monthly_loss_limit_r:
            self.month.halted = True
            return EntryPermission(False, False, "monthly_loss_limit")
        if self.day.realized_r <= self.daily_loss_limit_r:
            self.day.halted = True
            return EntryPermission(False, False, "daily_loss_limit")
        if (
            self.day.primary_take_profits
            >= self.maximum_primary_take_profits_per_day
        ):
            self.day.halted = True
            return EntryPermission(False, False, "two_primary_take_profits")
        if self.day.opened_positions >= self.maximum_positions_per_day:
            self.day.halted = True
            return EntryPermission(False, False, "five_positions")

        room = self.maximum_positions_per_day - self.day.opened_positions
        cover_enabled = room >= 2
        primary_loss = Decimal("-1")
        if self.day.realized_r + primary_loss <= self.daily_loss_limit_r:
            cover_enabled = False
        if self.month.realized_r + primary_loss <= self.pause_loss_threshold_r:
            cover_enabled = False
        if self.month.realized_r + primary_loss <= self.monthly_loss_limit_r:
            cover_enabled = False
        worst_case = Decimal("-2") if cover_enabled else primary_loss

        if self.day.realized_r + worst_case < self.daily_loss_limit_r:
            cover_enabled = False
            worst_case = primary_loss
        if self.month.realized_r + worst_case < self.monthly_loss_limit_r:
            cover_enabled = False
            worst_case = primary_loss
        if self.day.realized_r + worst_case < self.daily_loss_limit_r:
            return EntryPermission(False, False, "daily_risk_reservation")
        if self.month.realized_r + worst_case < self.monthly_loss_limit_r:
            return EntryPermission(False, False, "monthly_risk_reservation")
        return EntryPermission(True, cover_enabled, "allowed")

    def position_opened(self, trade_date: date) -> None:
        self.roll(trade_date)
        assert self.day is not None
        self.day.opened_positions += 1
        if self.day.opened_positions >= self.maximum_positions_per_day:
            self.day.halted = True

    def trade_closed(
        self,
        close_date: date,
        *,
        realized_r: Decimal,
        leg: int,
        take_profit: bool,
    ) -> None:
        self.roll(close_date)
        assert self.day is not None
        assert self.month is not None
        self.day.realized_r += realized_r
        self.month.realized_r += realized_r
        if leg == 1 and take_profit:
            self.day.primary_take_profits += 1
        if self.day.realized_r <= self.daily_loss_limit_r:
            self.day.halted = True
        if self.month.realized_r <= self.monthly_loss_limit_r:
            self.month.halted = True
        if self.month.realized_r >= self.monthly_profit_target_r:
            self.month.halted = True
        if self.month.realized_r <= self.pause_loss_threshold_r:
            self._paused_loss_date = close_date
        if (
            self.day.primary_take_profits
            >= self.maximum_primary_take_profits_per_day
        ):
            self.day.halted = True

    def status(self) -> dict[str, str | int | bool]:
        return {
            "daily_r": str(self.day.realized_r if self.day else Decimal("0")),
            "daily_positions": self.day.opened_positions if self.day else 0,
            "daily_primary_tps": self.day.primary_take_profits if self.day else 0,
            "daily_halted": self.day.halted if self.day else False,
            "monthly_r": str(
                self.month.realized_r if self.month else Decimal("0")
            ),
            "monthly_halted": self.month.halted if self.month else False,
            "monthly_paused_until_day_15": (
                self.month.paused_until_day_15 if self.month else False
            ),
        }


def strategy_accounting_r(
    *,
    exit_reason: str,
    leg: int,
    broker_realized_r: Decimal | None,
    primary_reward_risk: Decimal,
    cover_reward_risk: Decimal,
    mode: Literal["nominal", "broker_realized"] = "nominal",
) -> Decimal:
    if mode == "broker_realized":
        return broker_realized_r or Decimal("0")
    normalized = exit_reason.strip().lower()
    if normalized.startswith("take_profit"):
        return primary_reward_risk if leg == 1 else cover_reward_risk
    if normalized.startswith("stop_loss"):
        return Decimal("-1")
    return broker_realized_r or Decimal("0")
