from decimal import Decimal

from vex_contracts.enums import HigherTimeframeAccess
from vex_contracts.market import Bar
from vex_contracts.strategy import StrategySubscription
from vex_contracts.timeframes import Timeframe
from vex_strategy.forming import FormingBarCoordinator

NS = 1_000_000_000


class BoundaryStore:
    def boundaries(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_time_ns: int | None = None,
        end_time_ns: int | None = None,
    ) -> tuple[tuple[int, int], ...]:
        return ((0, 60 * 60 * NS), (60 * 60 * NS, 120 * 60 * NS))


def make_bar(sequence: int) -> Bar:
    open_time_ns = sequence * 60 * NS
    return Bar(
        symbol="XAUUSD",
        timeframe=Timeframe.M1,
        open_time_ns=open_time_ns,
        close_time_ns=open_time_ns + 60 * NS,
        open_ticks=260000 + sequence,
        high_ticks=260010 + sequence,
        low_ticks=259990 + sequence,
        close_ticks=260005 + sequence,
        tick_volume=100,
        real_volume=Decimal("0"),
        sequence=sequence,
    )


def test_forming_coordinator_uses_only_observed_execution_bars() -> None:
    coordinator = FormingBarCoordinator(
        BoundaryStore(),
        (
            StrategySubscription(
                symbol="XAUUSD",
                timeframe=Timeframe.H1,
                higher_timeframe_access=HigherTimeframeAccess.FORMING_ALLOWED,
            ),
        ),
        Timeframe.M1,
        0,
        120 * 60 * NS,
    )
    first = make_bar(0)
    second = make_bar(1)
    coordinator.ingest(first)
    coordinator.ingest(second)

    snapshot = coordinator.snapshots(second.close_time_ns)[0]

    assert snapshot.open_ticks == first.open_ticks
    assert snapshot.close_ticks == second.close_ticks
    assert snapshot.high_ticks == max(first.high_ticks, second.high_ticks)
    assert snapshot.low_ticks == min(first.low_ticks, second.low_ticks)
    assert snapshot.tick_volume == 200
    assert snapshot.observed_time_ns == second.close_time_ns
