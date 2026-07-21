from decimal import Decimal

import pytest

from vex_contracts.enums import HigherTimeframeAccess
from vex_contracts.market import Bar
from vex_contracts.strategy import StrategySubscription
from vex_contracts.strategy_runtime import FormingBar
from vex_contracts.timeframes import Timeframe
from vex_strategy.exceptions import StrategyMarketDataError
from vex_strategy.market import MarketDataView

NS = 1_000_000_000


def make_bar(sequence: int, close_ticks: int = 260000) -> Bar:
    open_time_ns = sequence * 60 * NS
    return Bar(
        symbol="XAUUSD",
        timeframe=Timeframe.M1,
        open_time_ns=open_time_ns,
        close_time_ns=open_time_ns + 60 * NS,
        open_ticks=close_ticks - 5,
        high_ticks=close_ticks + 10,
        low_ticks=close_ticks - 10,
        close_ticks=close_ticks,
        sequence=sequence,
    )


def test_market_view_rejects_future_bar() -> None:
    view = MarketDataView(
        (StrategySubscription(symbol="XAUUSD", timeframe=Timeframe.M1),),
        100,
    )
    view.set_time(60 * NS)

    with pytest.raises(StrategyMarketDataError):
        view.apply_closed_bars((make_bar(1),))


def test_market_view_maintains_bounded_history() -> None:
    view = MarketDataView(
        (StrategySubscription(symbol="XAUUSD", timeframe=Timeframe.M1),),
        2,
    )
    bars = (make_bar(0), make_bar(1), make_bar(2))
    view.set_time(bars[-1].close_time_ns)
    view.apply_closed_bars(bars)

    assert view.count("XAUUSD", Timeframe.M1) == 2
    assert view.latest("XAUUSD", Timeframe.M1) == bars[-1]
    assert view.history("XAUUSD", Timeframe.M1, 10) == bars[-2:]


def test_forming_bar_requires_explicit_access() -> None:
    closed_only = MarketDataView(
        (StrategySubscription(symbol="XAUUSD", timeframe=Timeframe.H1),),
        100,
    )
    closed_only.set_time(30 * 60 * NS)

    with pytest.raises(StrategyMarketDataError):
        closed_only.forming("XAUUSD", Timeframe.H1)

    forming_allowed = MarketDataView(
        (
            StrategySubscription(
                symbol="XAUUSD",
                timeframe=Timeframe.H1,
                higher_timeframe_access=HigherTimeframeAccess.FORMING_ALLOWED,
            ),
        ),
        100,
    )
    forming_allowed.set_time(30 * 60 * NS)
    forming = FormingBar(
        symbol="XAUUSD",
        timeframe=Timeframe.H1,
        open_time_ns=0,
        close_time_ns=60 * 60 * NS,
        observed_time_ns=30 * 60 * NS,
        open_ticks=260000,
        high_ticks=260100,
        low_ticks=259900,
        close_ticks=260050,
        real_volume=Decimal("0"),
    )
    forming_allowed.set_forming_bars((forming,))

    assert forming_allowed.forming("XAUUSD", Timeframe.H1) == forming
