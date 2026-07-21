from decimal import Decimal

from vex_broker.exceptions import BrokerConfigurationError
from vex_contracts.enums import CalculationMode, PositionSide, Side
from vex_contracts.execution import (
    CommissionConfig,
    FixedPerOrderCommissionConfig,
    NoCommissionConfig,
    PerLotPerSideCommissionConfig,
    PerLotRoundTurnCommissionConfig,
)
from vex_contracts.symbol import SymbolProfile

ZERO = Decimal("0")
HUNDRED = Decimal("100")
TEN_THOUSAND = Decimal("10000")
TWO = Decimal("2")


def points_to_ticks(points: int, profile: SymbolProfile) -> int:
    value = Decimal(points) * profile.point / profile.trade_tick_size
    if value != value.to_integral_value():
        raise BrokerConfigurationError("point amount is not aligned to trade_tick_size")
    return int(value)


def money_for_ticks(
    tick_distance: Decimal,
    volume_lots: Decimal,
    profile: SymbolProfile,
    favorable: bool,
) -> Decimal:
    tick_value = (
        profile.trade_tick_value_profit
        if favorable and profile.trade_tick_value_profit is not None
        else profile.trade_tick_value_loss
        if not favorable and profile.trade_tick_value_loss is not None
        else profile.trade_tick_value
    )
    return abs(tick_distance) * tick_value * volume_lots


def signed_price_pnl(
    side: PositionSide,
    entry_price_ticks: Decimal,
    exit_price_ticks: Decimal,
    volume_lots: Decimal,
    profile: SymbolProfile,
) -> Decimal:
    signed_ticks = (
        exit_price_ticks - entry_price_ticks
        if side is PositionSide.LONG
        else entry_price_ticks - exit_price_ticks
    )
    if signed_ticks == 0:
        return ZERO
    amount = money_for_ticks(signed_ticks, volume_lots, profile, signed_ticks > 0)
    return amount if signed_ticks > 0 else -amount


def spread_cost(
    spread_ticks: int,
    volume_lots: Decimal,
    profile: SymbolProfile,
) -> Decimal:
    return money_for_ticks(
        Decimal(spread_ticks) / TWO,
        volume_lots,
        profile,
        favorable=False,
    )


def slippage_cost(
    slippage_ticks: int,
    volume_lots: Decimal,
    profile: SymbolProfile,
) -> Decimal:
    return money_for_ticks(
        Decimal(abs(slippage_ticks)),
        volume_lots,
        profile,
        favorable=False,
    )


def commission_cost(
    config: CommissionConfig,
    side: Side,
    volume_lots: Decimal,
    price_ticks: int,
    profile: SymbolProfile,
) -> Decimal:
    del side
    if isinstance(config, NoCommissionConfig):
        return ZERO
    if isinstance(config, FixedPerOrderCommissionConfig):
        return config.amount
    if isinstance(config, PerLotPerSideCommissionConfig):
        return config.amount_per_lot * volume_lots
    if isinstance(config, PerLotRoundTurnCommissionConfig):
        return config.amount_per_lot * volume_lots / TWO
    price = profile.ticks_to_price(price_ticks)
    notional = price * profile.trade_contract_size * volume_lots
    return notional * config.rate_bps / TEN_THOUSAND


def required_margin(
    price_ticks: int,
    volume_lots: Decimal,
    profile: SymbolProfile,
    leverage: Decimal,
) -> Decimal:
    if profile.margin_initial > 0:
        return profile.margin_initial * volume_lots
    price = profile.ticks_to_price(price_ticks)
    if profile.calculation_mode in {CalculationMode.CFD, CalculationMode.CFD_INDEX}:
        return price * profile.trade_contract_size * volume_lots / leverage
    if profile.calculation_mode is CalculationMode.FOREX:
        return profile.trade_contract_size * volume_lots / leverage
    if profile.calculation_mode is CalculationMode.FUTURES:
        raise BrokerConfigurationError("futures require a non-zero margin_initial")
    raise BrokerConfigurationError(
        f"unsupported calculation mode: {profile.calculation_mode.value}"
    )
