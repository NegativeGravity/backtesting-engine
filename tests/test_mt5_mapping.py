import pytest

from vex_contracts.enums import CalculationMode, PositionMode, Side
from vex_mt5.exceptions import Mt5SnapshotError
from vex_mt5.mapping import (
    calculation_mode_from_mt5,
    order_type_for_side,
    position_mode_from_mt5,
)


def test_mt5_calculation_mode_mapping() -> None:
    assert calculation_mode_from_mt5(0) is CalculationMode.FOREX
    assert calculation_mode_from_mt5(3) is CalculationMode.CFD
    assert calculation_mode_from_mt5(4) is CalculationMode.CFD_INDEX
    assert calculation_mode_from_mt5(33) is CalculationMode.FUTURES
    for unsupported in (1, 32, 35, 36, 37, 38, 39, 64, 999):
        with pytest.raises(Mt5SnapshotError):
            calculation_mode_from_mt5(unsupported)


def test_mt5_account_and_order_mapping() -> None:
    assert position_mode_from_mt5(0) is PositionMode.NETTING
    assert position_mode_from_mt5(2) is PositionMode.HEDGING
    assert order_type_for_side(Side.BUY) == 0
    assert order_type_for_side(Side.SELL) == 1
