from __future__ import annotations

from vex_contracts.mt5 import Mt5SymbolSnapshot
from vex_contracts.serialization import fingerprint
from vex_contracts.symbol import SymbolProfile
from vex_mt5.mapping import calculation_mode_from_mt5


def profile_from_snapshot(snapshot: Mt5SymbolSnapshot) -> SymbolProfile:
    calculation_mode = calculation_mode_from_mt5(snapshot.trade_calc_mode)
    digest = fingerprint(
        {
            "symbol": snapshot.symbol,
            "calculation_mode": calculation_mode,
            "currency_base": snapshot.currency_base,
            "currency_profit": snapshot.currency_profit,
            "currency_margin": snapshot.currency_margin,
            "digits": snapshot.digits,
            "point": snapshot.point,
            "trade_tick_size": snapshot.trade_tick_size,
            "trade_tick_value": snapshot.trade_tick_value,
            "trade_tick_value_profit": snapshot.trade_tick_value_profit,
            "trade_tick_value_loss": snapshot.trade_tick_value_loss,
            "trade_contract_size": snapshot.trade_contract_size,
            "volume_min": snapshot.volume_min,
            "volume_max": snapshot.volume_max,
            "volume_step": snapshot.volume_step,
            "stops_level_points": snapshot.stops_level_points,
            "freeze_level_points": snapshot.freeze_level_points,
            "margin_initial": snapshot.margin_initial,
            "margin_maintenance": snapshot.margin_maintenance,
        }
    )
    return SymbolProfile(
        profile_id=f"mt5_{snapshot.symbol.lower()}_{digest[:12]}",
        version="1.0.0",
        symbol=snapshot.symbol,
        calculation_mode=calculation_mode,
        currency_base=snapshot.currency_base,
        currency_profit=snapshot.currency_profit,
        currency_margin=snapshot.currency_margin,
        digits=snapshot.digits,
        point=snapshot.point,
        trade_tick_size=snapshot.trade_tick_size,
        trade_tick_value=snapshot.trade_tick_value,
        trade_tick_value_profit=snapshot.trade_tick_value_profit,
        trade_tick_value_loss=snapshot.trade_tick_value_loss,
        trade_contract_size=snapshot.trade_contract_size,
        volume_min=snapshot.volume_min,
        volume_max=snapshot.volume_max,
        volume_step=snapshot.volume_step,
        stops_level_points=snapshot.stops_level_points,
        freeze_level_points=snapshot.freeze_level_points,
        margin_initial=snapshot.margin_initial,
        margin_maintenance=snapshot.margin_maintenance,
        metadata={
            "source": "mt5_symbol_info",
            "snapshot_digest": digest,
            "trade_mode": str(snapshot.trade_mode),
            "trade_execution_mode": str(snapshot.trade_execution_mode),
            "order_mode": str(snapshot.order_mode),
            "filling_mode": str(snapshot.filling_mode),
            "expiration_mode": str(snapshot.expiration_mode),
            "volume_limit": str(snapshot.volume_limit),
            "margin_hedged": str(snapshot.margin_hedged),
            "margin_hedged_use_leg": str(snapshot.margin_hedged_use_leg).lower(),
            "swap_mode": str(snapshot.swap_mode),
            "swap_long": str(snapshot.swap_long),
            "swap_short": str(snapshot.swap_short),
        },
    )
