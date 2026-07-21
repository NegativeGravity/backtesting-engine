from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from decimal import Decimal
from types import ModuleType
from typing import Any, cast

from vex_contracts.enums import Side
from vex_contracts.mt5 import (
    Mt5AccountSnapshot,
    Mt5CalculationSample,
    Mt5CompatibilitySnapshot,
    Mt5SymbolSnapshot,
    Mt5TerminalSnapshot,
)
from vex_contracts.mt5_bridge import Mt5BridgeConfig
from vex_contracts.serialization import fingerprint
from vex_mt5.exceptions import Mt5ConnectionError, Mt5SnapshotError
from vex_mt5.mapping import order_type_for_side, position_mode_from_mt5


def _mapping(value: object, label: str) -> dict[str, Any]:
    method = getattr(value, "_asdict", None)
    if not callable(method):
        raise Mt5SnapshotError(f"{label} did not return a named tuple")
    result = method()
    if not isinstance(result, dict):
        raise Mt5SnapshotError(f"{label} returned an invalid mapping")
    return cast(dict[str, Any], result)


def _required(data: dict[str, Any], key: str, label: str) -> Any:
    if key not in data:
        raise Mt5SnapshotError(f"{label} is missing field: {key}")
    return data[key]


def _load_mt5() -> ModuleType:
    try:
        return importlib.import_module("MetaTrader5")
    except ModuleNotFoundError as exc:
        raise Mt5ConnectionError(
            "MetaTrader5 is not installed. Run scripts\\install-mt5-bridge.ps1 on Windows."
        ) from exc


def collect_snapshot(
    config: Mt5BridgeConfig,
    mt5_module: ModuleType | None = None,
) -> Mt5CompatibilitySnapshot:
    mt5 = mt5_module or _load_mt5()
    initialize = getattr(mt5, "initialize", None)
    shutdown = getattr(mt5, "shutdown", None)
    if not callable(initialize) or not callable(shutdown):
        raise Mt5ConnectionError("MetaTrader5 module does not expose initialize/shutdown")
    password = os.getenv(config.password_env)
    kwargs: dict[str, object] = {
        "portable": config.portable,
        "timeout": int(config.timeout_ms),
    }
    if config.terminal_path:
        kwargs["path"] = config.terminal_path
    if config.login is not None:
        kwargs["login"] = int(config.login)
    if password:
        kwargs["password"] = password
    if config.server:
        kwargs["server"] = config.server
    if not bool(initialize(**kwargs)):
        error = getattr(mt5, "last_error", lambda: "unknown")()
        raise Mt5ConnectionError(f"MT5 initialize failed: {error}")
    try:
        terminal_data = _mapping(mt5.terminal_info(), "terminal_info")
        account_data = _mapping(mt5.account_info(), "account_info")
        symbols = tuple(_collect_symbol(mt5, symbol) for symbol in config.symbols)
        samples = tuple(
            sample for symbol in symbols for sample in _collect_samples(mt5, symbol, config)
        )
        captured_at = datetime.now(UTC)
        identity = fingerprint(
            {
                "captured_at": captured_at.isoformat(),
                "login": account_data.get("login"),
                "server": account_data.get("server"),
                "symbols": [item.symbol for item in symbols],
                "samples": samples,
            }
        )
        return Mt5CompatibilitySnapshot(
            snapshot_id=f"mt5_snapshot_{identity[:24]}",
            version=config.snapshot_version,
            captured_at=captured_at,
            terminal=Mt5TerminalSnapshot(
                name=str(_required(terminal_data, "name", "terminal_info")),
                company=str(_required(terminal_data, "company", "terminal_info")),
                build=int(_required(terminal_data, "build", "terminal_info")),
                connected=bool(_required(terminal_data, "connected", "terminal_info")),
                trade_allowed=bool(_required(terminal_data, "trade_allowed", "terminal_info")),
                tradeapi_disabled=bool(terminal_data.get("tradeapi_disabled", False)),
                path=str(_required(terminal_data, "path", "terminal_info")),
                data_path=str(_required(terminal_data, "data_path", "terminal_info")),
                commondata_path=str(_required(terminal_data, "commondata_path", "terminal_info")),
                maxbars=int(_required(terminal_data, "maxbars", "terminal_info")),
                ping_last_us=(
                    None
                    if terminal_data.get("ping_last") is None
                    else int(terminal_data["ping_last"])
                ),
            ),
            account=Mt5AccountSnapshot(
                login=int(_required(account_data, "login", "account_info")),
                server=str(_required(account_data, "server", "account_info")),
                company=str(_required(account_data, "company", "account_info")),
                name=str(_required(account_data, "name", "account_info")),
                currency=str(_required(account_data, "currency", "account_info")),
                leverage=Decimal(str(_required(account_data, "leverage", "account_info"))),
                position_mode=position_mode_from_mt5(
                    int(_required(account_data, "margin_mode", "account_info"))
                ),
                trade_allowed=bool(_required(account_data, "trade_allowed", "account_info")),
                trade_expert=bool(_required(account_data, "trade_expert", "account_info")),
                balance=Decimal(str(_required(account_data, "balance", "account_info"))),
                credit=Decimal(str(_required(account_data, "credit", "account_info"))),
                profit=Decimal(str(_required(account_data, "profit", "account_info"))),
                equity=Decimal(str(_required(account_data, "equity", "account_info"))),
                margin=Decimal(str(_required(account_data, "margin", "account_info"))),
                margin_free=Decimal(str(_required(account_data, "margin_free", "account_info"))),
                margin_level=(
                    None
                    if account_data.get("margin_level") is None
                    else Decimal(str(account_data["margin_level"]))
                ),
                margin_so_mode=int(_required(account_data, "margin_so_mode", "account_info")),
                margin_so_call=Decimal(
                    str(_required(account_data, "margin_so_call", "account_info"))
                ),
                margin_so_so=Decimal(str(_required(account_data, "margin_so_so", "account_info"))),
            ),
            symbols=symbols,
            calculation_samples=samples,
            metadata={"collector": "vex_mt5", "password_source": config.password_env},
        )
    finally:
        shutdown()


def _collect_symbol(mt5: ModuleType, symbol: str) -> Mt5SymbolSnapshot:
    select = getattr(mt5, "symbol_select", None)
    if not callable(select) or not bool(select(symbol, True)):
        error = getattr(mt5, "last_error", lambda: "unknown")()
        raise Mt5SnapshotError(f"symbol_select failed for {symbol}: {error}")
    info = _mapping(mt5.symbol_info(symbol), f"symbol_info({symbol})")
    tick = _mapping(mt5.symbol_info_tick(symbol), f"symbol_info_tick({symbol})")
    return Mt5SymbolSnapshot(
        symbol=symbol,
        path=str(info.get("path", symbol)),
        description=str(info.get("description", symbol)),
        currency_base=str(_required(info, "currency_base", f"symbol_info({symbol})")),
        currency_profit=str(_required(info, "currency_profit", f"symbol_info({symbol})")),
        currency_margin=str(_required(info, "currency_margin", f"symbol_info({symbol})")),
        digits=int(_required(info, "digits", f"symbol_info({symbol})")),
        point=Decimal(str(_required(info, "point", f"symbol_info({symbol})"))),
        spread_points=int(_required(info, "spread", f"symbol_info({symbol})")),
        spread_float=bool(info.get("spread_float", False)),
        trade_calc_mode=int(_required(info, "trade_calc_mode", f"symbol_info({symbol})")),
        trade_mode=int(_required(info, "trade_mode", f"symbol_info({symbol})")),
        trade_execution_mode=int(_required(info, "trade_exemode", f"symbol_info({symbol})")),
        order_mode=int(_required(info, "order_mode", f"symbol_info({symbol})")),
        filling_mode=int(_required(info, "filling_mode", f"symbol_info({symbol})")),
        expiration_mode=int(_required(info, "expiration_mode", f"symbol_info({symbol})")),
        stops_level_points=int(_required(info, "trade_stops_level", f"symbol_info({symbol})")),
        freeze_level_points=int(_required(info, "trade_freeze_level", f"symbol_info({symbol})")),
        trade_tick_size=Decimal(str(_required(info, "trade_tick_size", f"symbol_info({symbol})"))),
        trade_tick_value=Decimal(
            str(_required(info, "trade_tick_value", f"symbol_info({symbol})"))
        ),
        trade_tick_value_profit=Decimal(
            str(_required(info, "trade_tick_value_profit", f"symbol_info({symbol})"))
        ),
        trade_tick_value_loss=Decimal(
            str(_required(info, "trade_tick_value_loss", f"symbol_info({symbol})"))
        ),
        trade_contract_size=Decimal(
            str(_required(info, "trade_contract_size", f"symbol_info({symbol})"))
        ),
        volume_min=Decimal(str(_required(info, "volume_min", f"symbol_info({symbol})"))),
        volume_max=Decimal(str(_required(info, "volume_max", f"symbol_info({symbol})"))),
        volume_step=Decimal(str(_required(info, "volume_step", f"symbol_info({symbol})"))),
        volume_limit=Decimal(str(info.get("volume_limit", 0))),
        margin_initial=Decimal(str(info.get("margin_initial", 0))),
        margin_maintenance=Decimal(str(info.get("margin_maintenance", 0))),
        margin_hedged=Decimal(str(info.get("margin_hedged", 0))),
        margin_hedged_use_leg=bool(info.get("margin_hedged_use_leg", False)),
        swap_mode=int(info.get("swap_mode", 0)),
        swap_long=Decimal(str(info.get("swap_long", 0))),
        swap_short=Decimal(str(info.get("swap_short", 0))),
        bid=Decimal(str(_required(tick, "bid", f"symbol_info_tick({symbol})"))),
        ask=Decimal(str(_required(tick, "ask", f"symbol_info_tick({symbol})"))),
        last=Decimal(str(tick.get("last", 0))),
        time_msc=int(_required(tick, "time_msc", f"symbol_info_tick({symbol})")),
    )


def _collect_samples(
    mt5: ModuleType,
    symbol: Mt5SymbolSnapshot,
    config: Mt5BridgeConfig,
) -> tuple[Mt5CalculationSample, ...]:
    profit_fn = getattr(mt5, "order_calc_profit", None)
    margin_fn = getattr(mt5, "order_calc_margin", None)
    if not callable(profit_fn) or not callable(margin_fn):
        raise Mt5SnapshotError("MetaTrader5 module does not expose calculation functions")
    distance = Decimal(config.sample_distance_points) * symbol.point
    samples: list[Mt5CalculationSample] = []
    for side in (Side.BUY, Side.SELL):
        order_type = order_type_for_side(side)
        open_price = symbol.ask if side is Side.BUY else symbol.bid
        close_price = open_price + distance if side is Side.BUY else open_price - distance
        for volume in config.sample_volumes:
            profit = profit_fn(
                order_type,
                symbol.symbol,
                float(volume),
                float(open_price),
                float(close_price),
            )
            margin = margin_fn(order_type, symbol.symbol, float(volume), float(open_price))
            if profit is None or margin is None:
                error = getattr(mt5, "last_error", lambda: "unknown")()
                raise Mt5SnapshotError(
                    f"MT5 calculation failed for {symbol.symbol} {side.value} {volume}: {error}"
                )
            normalized_volume = str(volume).replace(".", "_")
            sample_id = f"sample_{symbol.symbol.lower()}_{side.value}_{normalized_volume}"
            samples.append(
                Mt5CalculationSample(
                    sample_id=sample_id,
                    symbol=symbol.symbol,
                    side=side,
                    volume_lots=volume,
                    open_price=open_price,
                    close_price=close_price,
                    mt5_profit=Decimal(str(profit)),
                    mt5_margin=Decimal(str(margin)),
                )
            )
    return tuple(samples)
