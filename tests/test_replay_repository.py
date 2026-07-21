from decimal import Decimal
from pathlib import Path

from vex_contracts.timeframes import Timeframe
from vex_replay.repository import ReplayRunRepository
from vex_replay.session import ReplaySession

RUN_ID = "run_xauusd_sdk_smoke_v1"


def test_replay_catalog_and_bootstrap() -> None:
    repository = ReplayRunRepository(Path.cwd())
    catalog = repository.catalog()
    target = next(run for run in catalog.runs if run.run_id == RUN_ID)
    assert target.available_timeframes == (
        Timeframe.M1,
        Timeframe.M5,
        Timeframe.M15,
        Timeframe.H1,
        Timeframe.H4,
        Timeframe.D1,
    )
    bootstrap = repository.bootstrap(RUN_ID)
    assert bootstrap.symbol == "XAUUSD"
    assert bootstrap.timeframe is Timeframe.M1
    assert bootstrap.bars
    assert bootstrap.account.balance == Decimal("100000")
    assert bootstrap.timeline


def test_replay_session_advances_and_seeks() -> None:
    repository = ReplayRunRepository(Path.cwd())
    session, bootstrap = ReplaySession.create(repository, RUN_ID)
    frame = session.step_forward(10)
    assert frame.cursor_sequence > bootstrap.cursor_sequence
    assert frame.bars
    assert frame.account is not None
    reset = session.seek_progress(Decimal("0.5"))
    assert Decimal("0.45") <= reset.progress <= Decimal("0.55")
    h1 = session.set_timeframe(Timeframe.H1)
    assert h1.timeframe is Timeframe.H1


def test_replay_state_reconstruction() -> None:
    repository = ReplayRunRepository(Path.cwd())
    descriptor = repository.descriptor(RUN_ID)
    orders, positions, fills, trades = repository.state_at(RUN_ID, descriptor.end_time_ns)
    assert len(orders) == 4
    assert not positions
    assert len(fills) == 2
    assert len(trades) == 1


def test_replay_analytics_full_and_cursor_reports() -> None:
    repository = ReplayRunRepository(Path.cwd())
    descriptor = repository.descriptor(RUN_ID)
    full = repository.analytics(RUN_ID)
    partial = repository.analytics(RUN_ID, descriptor.start_time_ns)
    assert full.run_id == RUN_ID
    assert full.equity_curve
    assert partial.end_time_ns <= full.end_time_ns
    comparison = repository.analytics_comparison((RUN_ID,))
    assert comparison.rows[0].run_id == RUN_ID
