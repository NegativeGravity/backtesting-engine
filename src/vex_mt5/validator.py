from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Literal

from vex_broker.calculations import required_margin, signed_price_pnl
from vex_contracts.enums import PositionMode
from vex_contracts.mt5 import (
    Mt5CompatibilityReport,
    Mt5CompatibilitySnapshot,
    Mt5ValidationCheck,
    Mt5ValidationTolerance,
)
from vex_contracts.run import BacktestRunConfig
from vex_contracts.serialization import fingerprint
from vex_contracts.symbol import SymbolProfile
from vex_mt5.mapping import calculation_mode_from_mt5
from vex_mt5.profile import profile_from_snapshot

type CheckCategory = Literal["terminal", "account", "symbol", "profit", "margin", "mapping"]

ZERO = Decimal("0")
TEN_THOUSAND = Decimal("10000")


def validate_snapshot(
    snapshot: Mt5CompatibilitySnapshot,
    profiles: tuple[SymbolProfile, ...],
    tolerance: Mt5ValidationTolerance | None = None,
    run_config: BacktestRunConfig | None = None,
    fail_on_warning: bool = False,
) -> Mt5CompatibilityReport:
    resolved_tolerance = tolerance or Mt5ValidationTolerance()
    profile_by_symbol = {profile.symbol: profile for profile in profiles}
    checks: list[Mt5ValidationCheck] = []
    checks.extend(_terminal_checks(snapshot))
    checks.extend(_account_checks(snapshot, run_config))
    generated_profiles: list[str] = []
    for symbol in snapshot.symbols:
        generated = profile_from_snapshot(symbol)
        generated_profiles.append(generated.profile_id)
        profile = profile_by_symbol.get(symbol.symbol)
        if profile is None:
            checks.append(
                Mt5ValidationCheck(
                    check_id=f"symbol_{symbol.symbol.lower()}_profile",
                    category="symbol",
                    status="failed",
                    symbol=symbol.symbol,
                    message="symbol profile is missing",
                )
            )
            continue
        checks.extend(_symbol_checks(symbol, profile, resolved_tolerance))
    for sample in snapshot.calculation_samples:
        profile = profile_by_symbol.get(sample.symbol)
        if profile is None:
            checks.append(
                Mt5ValidationCheck(
                    check_id=f"profit_{sample.sample_id}",
                    category="profit",
                    status="skipped",
                    symbol=sample.symbol,
                    sample_id=sample.sample_id,
                    message="profit validation skipped because the symbol profile is missing",
                )
            )
            checks.append(
                Mt5ValidationCheck(
                    check_id=f"margin_{sample.sample_id}",
                    category="margin",
                    status="skipped",
                    symbol=sample.symbol,
                    sample_id=sample.sample_id,
                    message="margin validation skipped because the symbol profile is missing",
                )
            )
            continue
        entry_ticks = profile.price_to_ticks(sample.open_price)
        exit_ticks = profile.price_to_ticks(sample.close_price)
        engine_profit = signed_price_pnl(
            sample.position_side,
            Decimal(entry_ticks),
            Decimal(exit_ticks),
            sample.volume_lots,
            profile,
        )
        checks.append(
            _money_check(
                check_id=f"profit_{sample.sample_id}",
                category="profit",
                message="engine profit matches MT5 order_calc_profit",
                expected=sample.mt5_profit,
                actual=engine_profit,
                tolerance=resolved_tolerance,
                symbol=sample.symbol,
                sample_id=sample.sample_id,
            )
        )
        engine_margin = required_margin(
            entry_ticks,
            sample.volume_lots,
            profile,
            snapshot.account.leverage,
        )
        checks.append(
            _money_check(
                check_id=f"margin_{sample.sample_id}",
                category="margin",
                message="engine margin matches MT5 order_calc_margin",
                expected=sample.mt5_margin,
                actual=engine_margin,
                tolerance=resolved_tolerance,
                symbol=sample.symbol,
                sample_id=sample.sample_id,
            )
        )
    passed = sum(check.status == "passed" for check in checks)
    warnings = sum(check.status == "warning" for check in checks)
    failed = sum(check.status == "failed" for check in checks)
    skipped = sum(check.status == "skipped" for check in checks)
    digest = fingerprint(
        {
            "snapshot_id": snapshot.snapshot_id,
            "profiles": profiles,
            "tolerance": resolved_tolerance,
            "checks": checks,
        }
    )
    return Mt5CompatibilityReport(
        report_id=f"mt5_report_{digest[:24]}",
        snapshot_id=snapshot.snapshot_id,
        compatible=failed == 0 and (not fail_on_warning or warnings == 0),
        passed_checks=passed,
        warning_checks=warnings,
        failed_checks=failed,
        skipped_checks=skipped,
        checks=tuple(checks),
        generated_profiles=tuple(generated_profiles),
        deterministic_digest=digest,
    )


def _terminal_checks(snapshot: Mt5CompatibilitySnapshot) -> list[Mt5ValidationCheck]:
    terminal = snapshot.terminal
    checks = [
        Mt5ValidationCheck(
            check_id="terminal_connected",
            category="terminal",
            status="passed" if terminal.connected else "failed",
            message=(
                "MT5 terminal is connected"
                if terminal.connected
                else "MT5 terminal is disconnected"
            ),
            expected="true",
            actual=str(terminal.connected).lower(),
        ),
        Mt5ValidationCheck(
            check_id="terminal_trade_allowed",
            category="terminal",
            status="passed" if terminal.trade_allowed else "warning",
            message=(
                "terminal trading is allowed"
                if terminal.trade_allowed
                else "terminal trading is disabled; snapshot validation remains available"
            ),
            expected="true",
            actual=str(terminal.trade_allowed).lower(),
        ),
        Mt5ValidationCheck(
            check_id="terminal_trade_api",
            category="terminal",
            status="failed" if terminal.tradeapi_disabled else "passed",
            message=(
                "MT5 external Python API is enabled"
                if not terminal.tradeapi_disabled
                else "MT5 external Python API is disabled"
            ),
            expected="false",
            actual=str(terminal.tradeapi_disabled).lower(),
        ),
    ]
    return checks


def _account_checks(
    snapshot: Mt5CompatibilitySnapshot,
    run_config: BacktestRunConfig | None,
) -> list[Mt5ValidationCheck]:
    account = snapshot.account
    checks = [
        Mt5ValidationCheck(
            check_id="account_trade_allowed",
            category="account",
            status="passed" if account.trade_allowed else "warning",
            message=(
                "account trading is allowed"
                if account.trade_allowed
                else "account trading is disabled; offline validation remains available"
            ),
            expected="true",
            actual=str(account.trade_allowed).lower(),
        ),
        Mt5ValidationCheck(
            check_id="account_expert_allowed",
            category="account",
            status="passed" if account.trade_expert else "warning",
            message=(
                "expert trading is allowed"
                if account.trade_expert
                else "expert trading is disabled"
            ),
            expected="true",
            actual=str(account.trade_expert).lower(),
        ),
    ]
    if run_config is None:
        checks.append(
            Mt5ValidationCheck(
                check_id="account_run_mapping",
                category="mapping",
                status="skipped",
                message="run configuration was not supplied",
            )
        )
        return checks
    checks.extend(
        [
            _exact_check(
                "account_currency",
                "account",
                "run account currency matches MT5 account currency",
                account.currency,
                run_config.account.currency,
            ),
            _decimal_check(
                "account_leverage",
                "account",
                "run leverage matches MT5 account leverage",
                account.leverage,
                run_config.account.leverage,
                Decimal("0"),
            ),
            _exact_check(
                "account_position_mode",
                "mapping",
                "run position mode matches MT5 margin mode",
                account.position_mode.value,
                run_config.account.position_mode.value,
            ),
            _decimal_check(
                "account_margin_call",
                "account",
                "run margin-call level matches MT5 account",
                account.margin_so_call,
                run_config.account.margin_call_level_percent,
                Decimal("0"),
            ),
            _decimal_check(
                "account_stop_out",
                "account",
                "run stop-out level matches MT5 account",
                account.margin_so_so,
                run_config.account.stop_out_level_percent,
                Decimal("0"),
            ),
        ]
    )
    if (
        account.position_mode is PositionMode.HEDGING
        and run_config.account.position_mode is PositionMode.NETTING
    ):
        checks.append(
            Mt5ValidationCheck(
                check_id="account_hedging_guard",
                category="mapping",
                status="failed",
                message="hedging MT5 account cannot be validated with a netting run",
            )
        )
    return checks


def _symbol_checks(
    symbol: object,
    profile: SymbolProfile,
    tolerance: Mt5ValidationTolerance,
) -> list[Mt5ValidationCheck]:
    from vex_contracts.mt5 import Mt5SymbolSnapshot

    snapshot = Mt5SymbolSnapshot.model_validate(symbol)
    pairs: tuple[tuple[str, object, object], ...] = (
        (
            "calculation_mode",
            calculation_mode_from_mt5(snapshot.trade_calc_mode),
            profile.calculation_mode,
        ),
        ("currency_base", snapshot.currency_base, profile.currency_base),
        ("currency_profit", snapshot.currency_profit, profile.currency_profit),
        ("currency_margin", snapshot.currency_margin, profile.currency_margin),
        ("digits", snapshot.digits, profile.digits),
        ("stops_level_points", snapshot.stops_level_points, profile.stops_level_points),
        ("freeze_level_points", snapshot.freeze_level_points, profile.freeze_level_points),
    )
    checks = [
        _exact_check(
            f"symbol_{snapshot.symbol.lower()}_{name}",
            "symbol",
            f"{name} matches MT5 symbol_info",
            _display(expected),
            _display(actual),
            snapshot.symbol,
        )
        for name, expected, actual in pairs
    ]
    decimal_pairs: tuple[tuple[str, Decimal, Decimal], ...] = (
        ("point", snapshot.point, profile.point),
        ("trade_tick_size", snapshot.trade_tick_size, profile.trade_tick_size),
        ("trade_tick_value", snapshot.trade_tick_value, profile.trade_tick_value),
        (
            "trade_tick_value_profit",
            snapshot.trade_tick_value_profit,
            profile.trade_tick_value_profit or profile.trade_tick_value,
        ),
        (
            "trade_tick_value_loss",
            snapshot.trade_tick_value_loss,
            profile.trade_tick_value_loss or profile.trade_tick_value,
        ),
        ("trade_contract_size", snapshot.trade_contract_size, profile.trade_contract_size),
        ("volume_min", snapshot.volume_min, profile.volume_min),
        ("volume_max", snapshot.volume_max, profile.volume_max),
        ("volume_step", snapshot.volume_step, profile.volume_step),
        ("margin_initial", snapshot.margin_initial, profile.margin_initial),
        ("margin_maintenance", snapshot.margin_maintenance, profile.margin_maintenance),
    )
    checks.extend(
        _decimal_check(
            f"symbol_{snapshot.symbol.lower()}_{name}",
            "symbol",
            f"{name} matches MT5 symbol_info",
            expected,
            actual,
            tolerance.decimal_absolute,
            snapshot.symbol,
        )
        for name, expected, actual in decimal_pairs
    )
    return checks


def _exact_check(
    check_id: str,
    category: CheckCategory,
    message: str,
    expected: object,
    actual: object,
    symbol: str | None = None,
) -> Mt5ValidationCheck:
    status = "passed" if expected == actual else "failed"
    return Mt5ValidationCheck(
        check_id=check_id,
        category=category,
        status=status,
        message=message if status == "passed" else f"{message} failed",
        symbol=symbol,
        expected=str(expected),
        actual=str(actual),
    )


def _decimal_check(
    check_id: str,
    category: CheckCategory,
    message: str,
    expected: Decimal,
    actual: Decimal,
    absolute_tolerance: Decimal,
    symbol: str | None = None,
) -> Mt5ValidationCheck:
    error = abs(actual - expected)
    status = "passed" if error <= absolute_tolerance else "failed"
    return Mt5ValidationCheck(
        check_id=check_id,
        category=category,
        status=status,
        message=message if status == "passed" else f"{message} failed",
        symbol=symbol,
        expected=str(expected),
        actual=str(actual),
        absolute_error=error,
        relative_error_bps=_relative_bps(expected, actual),
    )


def _money_check(
    *,
    check_id: str,
    category: CheckCategory,
    message: str,
    expected: Decimal,
    actual: Decimal,
    tolerance: Mt5ValidationTolerance,
    symbol: str,
    sample_id: str,
) -> Mt5ValidationCheck:
    error = abs(actual - expected)
    relative = _relative_bps(expected, actual)
    allowed = error <= tolerance.money_absolute or relative <= tolerance.money_relative_bps
    return Mt5ValidationCheck(
        check_id=check_id,
        category=category,
        status="passed" if allowed else "failed",
        message=message if allowed else f"{message} failed",
        symbol=symbol,
        sample_id=sample_id,
        expected=str(expected),
        actual=str(actual),
        absolute_error=error,
        relative_error_bps=relative,
    )


def _display(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _relative_bps(expected: Decimal, actual: Decimal) -> Decimal:
    denominator = abs(expected)
    if denominator == ZERO:
        return ZERO if actual == ZERO else Decimal("Infinity")
    return abs(actual - expected) / denominator * TEN_THOUSAND
