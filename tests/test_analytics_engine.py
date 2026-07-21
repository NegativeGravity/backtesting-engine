from decimal import Decimal

from vex_analytics.engine import AnalyticsEngine
from vex_contracts.analytics import AnalyticsConfig, EquityCurvePoint
from vex_contracts.enums import PositionSide
from vex_contracts.positions import Trade

DAY_NS = 86_400_000_000_000


def trade(
    index: int,
    pnl: str,
    side: PositionSide,
    entry_day: int,
    exit_day: int,
    commission: str = "1",
    spread: str = "2",
) -> Trade:
    net = Decimal(pnl)
    costs = Decimal(commission) + Decimal(spread)
    return Trade(
        trade_id=f"trade_{index}",
        position_id=f"position_{index}",
        run_id="run_analytics",
        strategy_instance_id="strategy_analytics",
        symbol="XAUUSD",
        side=side,
        volume_lots=Decimal("1"),
        entry_time_ns=entry_day * DAY_NS,
        exit_time_ns=exit_day * DAY_NS,
        entry_price_ticks=Decimal("200000"),
        exit_price_ticks=Decimal("200100"),
        gross_pnl=net + costs,
        commission=Decimal(commission),
        spread_cost=Decimal(spread),
        slippage_cost=Decimal("0"),
        swap=Decimal("0"),
        net_pnl=net,
        initial_risk=Decimal("50"),
        realized_r_multiple=net / Decimal("50"),
        mae=Decimal("20"),
        mfe=Decimal("80"),
        intrabar_ambiguous=index == 4,
        exit_reason="take_profit" if net > 0 else "stop_loss",
    )


def equity(day: int, balance: str, value: str, peak: str) -> EquityCurvePoint:
    equity_value = Decimal(value)
    peak_value = Decimal(peak)
    drawdown = peak_value - equity_value
    return EquityCurvePoint(
        time_ns=day * DAY_NS,
        balance=Decimal(balance),
        equity=equity_value,
        floating_pnl=equity_value - Decimal(balance),
        margin=Decimal("0"),
        drawdown_amount=drawdown,
        drawdown_percent=drawdown / peak_value * Decimal("100") if peak_value else Decimal("0"),
    )


def test_analytics_report_calculates_performance_and_risk() -> None:
    trades = (
        trade(1, "100", PositionSide.LONG, 1, 2),
        trade(2, "-50", PositionSide.SHORT, 2, 3),
        trade(3, "150", PositionSide.LONG, 4, 5),
        trade(4, "-25", PositionSide.SHORT, 6, 7),
    )
    curve = (
        equity(1, "10000", "10000", "10000"),
        equity(2, "10100", "10100", "10100"),
        equity(3, "10050", "10050", "10100"),
        equity(4, "10050", "10020", "10100"),
        equity(5, "10200", "10200", "10200"),
        equity(6, "10200", "10180", "10200"),
        equity(7, "10175", "10175", "10200"),
    )
    report = AnalyticsEngine().calculate(
        run_id="run_analytics",
        currency="USD",
        initial_balance=Decimal("10000"),
        start_time_ns=DAY_NS,
        end_time_ns=7 * DAY_NS,
        trades=trades,
        equity_curve=curve,
        config=AnalyticsConfig(rolling_window_days=3),
    )

    assert report.performance.net_pnl == Decimal("175")
    assert report.performance.gross_profit == Decimal("250")
    assert report.performance.gross_loss == Decimal("75")
    assert report.performance.profit_factor == Decimal("250") / Decimal("75")
    assert report.trades.total_trades == 4
    assert report.trades.win_rate_percent == Decimal("50")
    assert report.trades.ambiguous_trade_count == 1
    assert report.costs.total_cost == Decimal("12")
    assert report.risk.max_drawdown_amount == Decimal("80")
    assert report.risk.max_drawdown_percent > 0
    assert report.side_breakdown[0].trade_count == 2
    assert report.monthly_performance
    assert report.daily_returns
    assert report.rolling_metrics
    assert report.pnl_distribution
    assert report.drawdown_episodes


def test_analytics_report_handles_empty_trade_set() -> None:
    curve = (equity(1, "10000", "10000", "10000"),)
    report = AnalyticsEngine().calculate(
        run_id="run_empty",
        currency="USD",
        initial_balance=Decimal("10000"),
        start_time_ns=DAY_NS,
        end_time_ns=DAY_NS,
        trades=(),
        equity_curve=curve,
    )

    assert report.performance.net_pnl == 0
    assert report.performance.profit_factor is None
    assert report.trades.total_trades == 0
    assert report.costs.total_cost == 0
    assert report.side_breakdown == ()
    assert report.pnl_distribution == ()
