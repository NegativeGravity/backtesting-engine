from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal

from vex_contracts.enums import HigherTimeframeAccess
from vex_contracts.market import Bar
from vex_contracts.strategy import StrategySubscription
from vex_contracts.strategy_runtime import FormingBar
from vex_contracts.timeframes import Timeframe
from vex_data_engine.catalog import ParquetBarStore


@dataclass(slots=True)
class _Aggregate:
    symbol: str
    timeframe: Timeframe
    open_time_ns: int
    close_time_ns: int
    open_ticks: int
    high_ticks: int
    low_ticks: int
    close_ticks: int
    tick_volume: int
    real_volume: Decimal
    source_spread_points: int
    observed_time_ns: int

    @classmethod
    def from_bar(
        cls,
        bar: Bar,
        timeframe: Timeframe,
        open_time_ns: int,
        close_time_ns: int,
    ) -> "_Aggregate":
        return cls(
            symbol=bar.symbol,
            timeframe=timeframe,
            open_time_ns=open_time_ns,
            close_time_ns=close_time_ns,
            open_ticks=bar.open_ticks,
            high_ticks=bar.high_ticks,
            low_ticks=bar.low_ticks,
            close_ticks=bar.close_ticks,
            tick_volume=bar.tick_volume,
            real_volume=bar.real_volume,
            source_spread_points=bar.source_spread_points,
            observed_time_ns=bar.close_time_ns,
        )

    def update(self, bar: Bar) -> None:
        self.high_ticks = max(self.high_ticks, bar.high_ticks)
        self.low_ticks = min(self.low_ticks, bar.low_ticks)
        self.close_ticks = bar.close_ticks
        self.tick_volume += bar.tick_volume
        self.real_volume += bar.real_volume
        self.source_spread_points = bar.source_spread_points
        self.observed_time_ns = bar.close_time_ns

    def snapshot(self) -> FormingBar:
        return FormingBar(
            symbol=self.symbol,
            timeframe=self.timeframe,
            open_time_ns=self.open_time_ns,
            close_time_ns=self.close_time_ns,
            observed_time_ns=self.observed_time_ns,
            open_ticks=self.open_ticks,
            high_ticks=self.high_ticks,
            low_ticks=self.low_ticks,
            close_ticks=self.close_ticks,
            tick_volume=self.tick_volume,
            real_volume=self.real_volume,
            source_spread_points=self.source_spread_points,
        )


@dataclass(frozen=True, slots=True)
class _BoundarySeries:
    opens: tuple[int, ...]
    closes: tuple[int, ...]

    def containing(self, bar: Bar) -> tuple[int, int] | None:
        index = bisect_right(self.opens, bar.open_time_ns) - 1
        if index < 0:
            return None
        open_time_ns = self.opens[index]
        close_time_ns = self.closes[index]
        if bar.open_time_ns < open_time_ns or bar.close_time_ns > close_time_ns:
            return None
        return open_time_ns, close_time_ns


class FormingBarCoordinator:
    def __init__(
        self,
        store: ParquetBarStore,
        subscriptions: tuple[StrategySubscription, ...],
        execution_timeframe: Timeframe,
        start_time_ns: int,
        end_time_ns: int,
    ) -> None:
        targets = tuple(
            subscription
            for subscription in subscriptions
            if subscription.higher_timeframe_access is HigherTimeframeAccess.FORMING_ALLOWED
            and subscription.timeframe is not execution_timeframe
        )
        self._targets = {
            (target.symbol, target.timeframe): self._load_boundaries(
                store,
                target.symbol,
                target.timeframe,
                start_time_ns,
                end_time_ns,
            )
            for target in targets
        }
        self._aggregates: dict[tuple[str, Timeframe], _Aggregate] = {}
        self._warmup_start_time_ns = min(
            (series.opens[0] for series in self._targets.values() if series.opens),
            default=start_time_ns,
        )

    @property
    def warmup_start_time_ns(self) -> int:
        return self._warmup_start_time_ns

    def ingest(self, bar: Bar) -> None:
        for key, boundaries in self._targets.items():
            symbol, timeframe = key
            if symbol != bar.symbol:
                continue
            boundary = boundaries.containing(bar)
            if boundary is None:
                self._aggregates.pop(key, None)
                continue
            open_time_ns, close_time_ns = boundary
            if bar.close_time_ns >= close_time_ns:
                self._aggregates.pop(key, None)
                continue
            aggregate = self._aggregates.get(key)
            if aggregate is None or aggregate.open_time_ns != open_time_ns:
                self._aggregates[key] = _Aggregate.from_bar(
                    bar,
                    timeframe,
                    open_time_ns,
                    close_time_ns,
                )
                continue
            aggregate.update(bar)

    def snapshots(self, event_time_ns: int) -> tuple[FormingBar, ...]:
        return tuple(
            aggregate.snapshot().model_copy(update={"observed_time_ns": event_time_ns})
            for _, aggregate in sorted(
                self._aggregates.items(),
                key=lambda item: (item[0][0], item[0][1].value),
            )
            if aggregate.observed_time_ns <= event_time_ns < aggregate.close_time_ns
        )

    @staticmethod
    def _load_boundaries(
        store: ParquetBarStore,
        symbol: str,
        timeframe: Timeframe,
        start_time_ns: int,
        end_time_ns: int,
    ) -> _BoundarySeries:
        boundaries = store.boundaries(
            symbol,
            timeframe,
            start_time_ns,
            end_time_ns,
        )
        return _BoundarySeries(
            opens=tuple(item[0] for item in boundaries),
            closes=tuple(item[1] for item in boundaries),
        )
