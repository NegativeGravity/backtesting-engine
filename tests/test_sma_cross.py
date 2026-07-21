import pytest
from pydantic import ValidationError

from vex_example_strategies.sma_cross import SmaCrossParameters


def test_sma_cross_parameters_validate_periods() -> None:
    params = SmaCrossParameters(fast_period=10, slow_period=30)
    assert params.fast_period == 10
    with pytest.raises(ValidationError):
        SmaCrossParameters(fast_period=30, slow_period=10)
