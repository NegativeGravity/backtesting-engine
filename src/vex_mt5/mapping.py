from vex_contracts.enums import CalculationMode, PositionMode, Side
from vex_mt5.exceptions import Mt5SnapshotError

MT5_CALC_FOREX = {0}
MT5_CALC_FUTURES = {2, 33, 34}
MT5_CALC_CFD = {3, 5}
MT5_CALC_CFD_INDEX = {4}
MT5_MARGIN_MODE_NETTING = {0, 1}
MT5_MARGIN_MODE_HEDGING = {2}
MT5_ORDER_TYPE_BUY = 0
MT5_ORDER_TYPE_SELL = 1
MT5_POSITION_TYPE_BUY = 0
MT5_POSITION_TYPE_SELL = 1


def calculation_mode_from_mt5(value: int) -> CalculationMode:
    if value in MT5_CALC_FOREX:
        return CalculationMode.FOREX
    if value in MT5_CALC_FUTURES:
        return CalculationMode.FUTURES
    if value in MT5_CALC_CFD:
        return CalculationMode.CFD
    if value in MT5_CALC_CFD_INDEX:
        return CalculationMode.CFD_INDEX
    raise Mt5SnapshotError(f"unsupported MT5 trade_calc_mode: {value}")


def position_mode_from_mt5(value: int) -> PositionMode:
    if value in MT5_MARGIN_MODE_NETTING:
        return PositionMode.NETTING
    if value in MT5_MARGIN_MODE_HEDGING:
        return PositionMode.HEDGING
    raise Mt5SnapshotError(f"unsupported MT5 margin_mode: {value}")


def order_type_for_side(side: Side) -> int:
    return MT5_ORDER_TYPE_BUY if side is Side.BUY else MT5_ORDER_TYPE_SELL


def position_type_for_side(side: Side) -> int:
    return MT5_POSITION_TYPE_BUY if side is Side.BUY else MT5_POSITION_TYPE_SELL
