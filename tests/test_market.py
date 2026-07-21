import pytest
from pydantic import ValidationError

from vex_contracts.market import Bar


def test_bar_accepts_valid_m1_duration() -> None:
    bar = Bar(
        symbol="XAUUSD",
        timeframe="M1",
        open_time_ns=0,
        close_time_ns=60_000_000_000,
        open_ticks=100,
        high_ticks=110,
        low_ticks=90,
        close_ticks=105,
        sequence=0,
    )

    assert bar.close_ticks == 105


def test_bar_rejects_invalid_ohlc() -> None:
    with pytest.raises(ValidationError):
        Bar(
            symbol="XAUUSD",
            timeframe="M1",
            open_time_ns=0,
            close_time_ns=60_000_000_000,
            open_ticks=100,
            high_ticks=95,
            low_ticks=90,
            close_ticks=105,
            sequence=0,
        )
