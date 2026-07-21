from dataclasses import dataclass
from decimal import Decimal

from vex_broker.exceptions import BrokerConfigurationError
from vex_contracts.enums import PriceBasis, Side
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
        spread_points: int,
    ) -> None:
        if price_basis is not PriceBasis.BID:
            raise BrokerConfigurationError("phase 2 supports bid-based candle datasets only")
        spread_price = Decimal(spread_points) * profile.point
        spread_ticks = spread_price / profile.trade_tick_size
        if spread_ticks != spread_ticks.to_integral_value():
            raise BrokerConfigurationError("fixed spread is not aligned to trade_tick_size")
        self._spread_ticks = int(spread_ticks)

    @property
    def spread_ticks(self) -> int:
        return self._spread_ticks

    def resolve(self, bar: Bar) -> ResolvedBar:
        bid = SideBar(
            open_ticks=bar.open_ticks,
            high_ticks=bar.high_ticks,
            low_ticks=bar.low_ticks,
            close_ticks=bar.close_ticks,
        )
        ask = SideBar(
            open_ticks=bar.open_ticks + self._spread_ticks,
            high_ticks=bar.high_ticks + self._spread_ticks,
            low_ticks=bar.low_ticks + self._spread_ticks,
            close_ticks=bar.close_ticks + self._spread_ticks,
        )
        return ResolvedBar(bid=bid, ask=ask, spread_ticks=self._spread_ticks)

    @staticmethod
    def executable_open(resolved: ResolvedBar, side: Side) -> int:
        return resolved.ask.open_ticks if side is Side.BUY else resolved.bid.open_ticks

    @staticmethod
    def executable_close(resolved: ResolvedBar, side: Side) -> int:
        return resolved.ask.close_ticks if side is Side.BUY else resolved.bid.close_ticks
