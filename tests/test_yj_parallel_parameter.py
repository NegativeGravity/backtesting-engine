from __future__ import annotations

from strategies.yj_box_breakout.strategy import YjBoxBreakoutParameters


def test_parallel_parameter_is_accepted() -> None:
    parameters = YjBoxBreakoutParameters(
        allow_overlapping_daily_chains=True
    )
    assert parameters.allow_overlapping_daily_chains is True


def test_parallel_parameter_defaults_to_true() -> None:
    parameters = YjBoxBreakoutParameters()
    assert parameters.allow_overlapping_daily_chains is True
