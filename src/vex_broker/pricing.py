from dataclasses import dataclass

from vex_broker.exceptions import BrokerConfigurationError
from vex_contracts.enums import PriceBasis, Side, SpreadMode
from vex_contracts.execution import SpreadConfig
from vex_contracts.market import Bar
from vex_contracts.symbol import SymbolProfile


@dataclass(frozen=True, slots=True)
class SideBar:
    open_ticks: int
    high_ticks: int
    low_ticks: int
    close_ticks: int


@dataclass(frozen=True, slots=True)
class ResolvedBar:
    bid: SideBar
    ask: SideBar
    spread_ticks: int


class PriceResolver:
    def __init__(
        self,
        profile: SymbolProfile,
        price_basis: PriceBasis,
        spread: SpreadConfig,
    ) -> None:
        if price_basis is not PriceBasis.BID:
            raise BrokerConfigurationError("bid-based candle datasets are required")
        points_per_tick = profile.trade_tick_size / profile.point
        if points_per_tick != points_per_tick.to_integral_value() or points_per_tick <= 0:
            raise BrokerConfigurationError("trade_tick_size must be an integer multiple of point")
        self._points_per_tick = int(points_per_tick)
        self._spread = spread
        if spread.mode is SpreadMode.FIXED:
            self._fixed_spread_ticks = self._strict_points_to_ticks(spread.points)
        else:
            self._fixed_spread_ticks = None

    @property
    def spread_ticks(self) -> int:
        if self._fixed_spread_ticks is None:
            raise BrokerConfigurationError(
                "historical spread varies by bar; use ResolvedBar.spread_ticks"
            )
        return self._fixed_spread_ticks

    def resolve(self, bar: Bar) -> ResolvedBar:
        spread_ticks = self._spread_ticks_for_bar(bar)
        bid = SideBar(
            open_ticks=bar.open_ticks,
            high_ticks=bar.high_ticks,
            low_ticks=bar.low_ticks,
            close_ticks=bar.close_ticks,
        )
        ask = SideBar(
            open_ticks=bar.open_ticks + spread_ticks,
            high_ticks=bar.high_ticks + spread_ticks,
            low_ticks=bar.low_ticks + spread_ticks,
            close_ticks=bar.close_ticks + spread_ticks,
        )
        return ResolvedBar(bid=bid, ask=ask, spread_ticks=spread_ticks)

    def _spread_ticks_for_bar(self, bar: Bar) -> int:
        if self._spread.mode is SpreadMode.FIXED:
            return self._fixed_spread_ticks or 0
        points = bar.source_spread_points
        if points == 0 and self._spread.use_fallback_when_zero:
            points = self._spread.fallback_points
        points = max(points, self._spread.minimum_points)
        if self._spread.maximum_points is not None:
            points = min(points, self._spread.maximum_points)
        return self._rounded_points_to_ticks(points)

    def _strict_points_to_ticks(self, points: int) -> int:
        quotient, remainder = divmod(points, self._points_per_tick)
        if remainder:
            raise BrokerConfigurationError("fixed spread is not aligned to trade_tick_size")
        return quotient

    def _rounded_points_to_ticks(self, points: int) -> int:
        quotient, remainder = divmod(points, self._points_per_tick)
        return quotient + int(remainder > 0)

    @staticmethod
    def executable_open(resolved: ResolvedBar, side: Side) -> int:
        return resolved.ask.open_ticks if side is Side.BUY else resolved.bid.open_ticks

    @staticmethod
    def executable_close(resolved: ResolvedBar, side: Side) -> int:
        return resolved.ask.close_ticks if side is Side.BUY else resolved.bid.close_ticks
