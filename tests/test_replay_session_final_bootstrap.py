from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from vex_contracts.timeframes import Timeframe
from vex_replay.session import ReplaySession


class _RepositoryStub:
    def __init__(self) -> None:
        self.bootstrap_arguments: dict[str, Any] | None = None

    def descriptor(self, run_id: str) -> SimpleNamespace:
        assert run_id == "run_final_chart_test"
        return SimpleNamespace(end_time_ns=9_000)

    def bootstrap(
        self,
        run_id: str,
        symbol: str | None,
        timeframe: Timeframe | None,
        cursor_time_ns: int | None = None,
        history_count: int = 500,
    ) -> SimpleNamespace:
        self.bootstrap_arguments = {
            "run_id": run_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "cursor_time_ns": cursor_time_ns,
            "history_count": history_count,
        }
        return SimpleNamespace(
            symbol="XAUUSD",
            timeframe=Timeframe.M15,
            cursor_sequence=600,
            cursor_time_ns=9_000,
        )


def test_finalized_replay_bootstraps_at_the_end_with_a_bounded_window() -> None:
    repository = _RepositoryStub()

    session, bootstrap = ReplaySession.create(
        repository,  # type: ignore[arg-type]
        "run_final_chart_test",
        start_at_end=True,
    )

    assert bootstrap.cursor_time_ns == 9_000
    assert session.cursor_time_ns == 9_000
    assert repository.bootstrap_arguments == {
        "run_id": "run_final_chart_test",
        "symbol": None,
        "timeframe": None,
        "cursor_time_ns": 9_000,
        "history_count": 5_000,
    }
