from collections import deque
from collections.abc import Iterable

from vex_contracts.enums import HigherTimeframeAccess
from vex_contracts.market import Bar
from vex_contracts.strategy import StrategySubscription
from vex_contracts.strategy_runtime import FormingBar
from vex_contracts.timeframes import Timeframe
from vex_strategy.exceptions import StrategyMarketDataError


class MarketDataView:
    def __init__(
        self,
        subscriptions: tuple[StrategySubscription, ...],
        history_limit_per_series: int,
    ) -> None:
        self._subscriptions = {
            (subscription.symbol, subscription.timeframe): subscription
            for subscription in subscriptions
        }
        self._history_limit = history_limit_per_series
        self._history: dict[tuple[str, Timeframe], deque[Bar]] = {
            key: deque(maxlen=history_limit_per_series) for key in self._subscriptions
        }
        self._forming: dict[tuple[str, Timeframe], FormingBar] = {}
        self._current_time_ns = 0
        self._closed_at: tuple[Bar, ...] = ()

    @property
    def current_time_ns(self) -> int:
        return self._current_time_ns

    def set_time(self, time_ns: int) -> None:
        if time_ns < self._current_time_ns:
            raise StrategyMarketDataError("strategy clock cannot move backward")
        self._current_time_ns = time_ns

    def apply_closed_bars(self, bars: Iterable[Bar]) -> None:
        applied: list[Bar] = []
        for bar in bars:
            key = (bar.symbol, bar.timeframe)
            history = self._history.get(key)
            if history is None:
                raise StrategyMarketDataError(
                    f"bar is not subscribed: {bar.symbol}:{bar.timeframe.value}"
                )
            if bar.close_time_ns > self._current_time_ns:
                raise StrategyMarketDataError("bar closes after the strategy clock")
            if history:
                previous = history[-1]
                if bar.close_time_ns < previous.close_time_ns:
                    raise StrategyMarketDataError("closed bars must be applied chronologically")
                if bar.close_time_ns == previous.close_time_ns:
                    if bar != previous:
                        raise StrategyMarketDataError("conflicting bars share the same close time")
                    continue
            history.append(bar)
            applied.append(bar)
        self._closed_at = tuple(applied)

    def set_forming_bars(self, bars: Iterable[FormingBar]) -> None:
        next_forming: dict[tuple[str, Timeframe], FormingBar] = {}
        for bar in bars:
            timeframe = bar.timeframe
            key = (bar.symbol, timeframe)
            subscription = self._subscriptions.get(key)
            if subscription is None:
                raise StrategyMarketDataError(
                    f"forming bar is not subscribed: {bar.symbol}:{timeframe.value}"
                )
            if subscription.higher_timeframe_access is not HigherTimeframeAccess.FORMING_ALLOWED:
                raise StrategyMarketDataError(
                    f"forming access is disabled: {bar.symbol}:{timeframe.value}"
                )
            if bar.observed_time_ns != self._current_time_ns:
                raise StrategyMarketDataError(
                    "forming bar observation must match the strategy clock"
                )
            next_forming[key] = bar
        self._forming = next_forming

    def latest(self, symbol: str, timeframe: Timeframe, offset: int = 0) -> Bar | None:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        history = self._require_history(symbol, timeframe)
        if offset >= len(history):
            return None
        return history[-1 - offset]

    def history(self, symbol: str, timeframe: Timeframe, count: int) -> tuple[Bar, ...]:
        if count <= 0:
            raise ValueError("count must be positive")
        history = self._require_history(symbol, timeframe)
        if count >= len(history):
            return tuple(history)
        return tuple(list(history)[-count:])

    def forming(self, symbol: str, timeframe: Timeframe) -> FormingBar | None:
        subscription = self._subscriptions.get((symbol, timeframe))
        if subscription is None:
            raise StrategyMarketDataError(f"series is not subscribed: {symbol}:{timeframe.value}")
        if subscription.higher_timeframe_access is not HigherTimeframeAccess.FORMING_ALLOWED:
            raise StrategyMarketDataError(f"forming access is disabled: {symbol}:{timeframe.value}")
        return self._forming.get((symbol, timeframe))

    def closed_at_current_time(self) -> tuple[Bar, ...]:
        return self._closed_at

    def count(self, symbol: str, timeframe: Timeframe) -> int:
        return len(self._require_history(symbol, timeframe))

    def _require_history(self, symbol: str, timeframe: Timeframe) -> deque[Bar]:
        try:
            return self._history[(symbol, timeframe)]
        except KeyError as exc:
            raise StrategyMarketDataError(
                f"series is not subscribed: {symbol}:{timeframe.value}"
            ) from exc
