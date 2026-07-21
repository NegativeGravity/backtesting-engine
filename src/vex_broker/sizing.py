from decimal import ROUND_FLOOR, Decimal

from vex_broker.calculations import money_for_ticks
from vex_broker.exceptions import OrderRejectedError
from vex_contracts.enums import PositionSizingMode
from vex_contracts.risk import PositionSizingConfig
from vex_contracts.symbol import SymbolProfile

HUNDRED = Decimal("100")


class PositionSizer:
    @staticmethod
    def size(
        config: PositionSizingConfig,
        equity: Decimal,
        entry_price_ticks: int,
        stop_loss_ticks: int | None,
        profile: SymbolProfile,
        requested_volume_lots: Decimal | None = None,
    ) -> Decimal:
        if config.mode is PositionSizingMode.STRATEGY_DEFINED:
            if requested_volume_lots is None:
                raise OrderRejectedError("strategy-defined sizing requires requested volume")
            return PositionSizer._normalize(requested_volume_lots, profile)
        if config.mode is PositionSizingMode.FIXED_LOT:
            return PositionSizer._normalize(config.volume_lots, profile)
        if stop_loss_ticks is None:
            raise OrderRejectedError("risk-based sizing requires stop_loss_ticks")
        stop_distance = Decimal(abs(entry_price_ticks - stop_loss_ticks))
        if stop_distance == 0:
            raise OrderRejectedError("risk-based sizing requires non-zero stop distance")
        risk_money = (
            equity * config.risk_percent / HUNDRED
            if config.mode is PositionSizingMode.RISK_PERCENT
            else config.cash_amount
        )
        risk_per_lot = money_for_ticks(
            stop_distance,
            Decimal("1"),
            profile,
            favorable=False,
        )
        if risk_per_lot <= 0:
            raise OrderRejectedError("risk per lot must be positive")
        return PositionSizer._normalize(risk_money / risk_per_lot, profile)

    @staticmethod
    def _normalize(value: Decimal, profile: SymbolProfile) -> Decimal:
        if value < profile.volume_min:
            raise OrderRejectedError("calculated volume is below volume_min")
        capped = min(value, profile.volume_max)
        steps = ((capped - profile.volume_min) / profile.volume_step).to_integral_value(
            rounding=ROUND_FLOOR
        )
        normalized = profile.volume_min + steps * profile.volume_step
        if normalized < profile.volume_min:
            raise OrderRejectedError("calculated volume is below volume_min")
        return normalized
