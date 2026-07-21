import hashlib
import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from vex_contracts.analytics import (
    AnalyticsConfig,
    AnalyticsReport,
    BreakdownRow,
    DistributionBucket,
    DrawdownEpisode,
    EquityCurvePoint,
    ExecutionCostMetrics,
    PerformanceMetrics,
    PeriodicPerformance,
    PeriodReturnPoint,
    RiskMetrics,
    RollingMetricPoint,
    TradeBehaviorMetrics,
)
from vex_contracts.identifiers import CurrencyCode
from vex_contracts.positions import Trade
from vex_contracts.serialization import canonical_json

_NS_PER_MINUTE = 60_000_000_000
_NS_PER_DAY = 86_400_000_000_000
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_HUNDRED = Decimal("100")


def _decimal(value: float | int | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if not math.isfinite(float(value)):
        raise ValueError("analytics values must be finite")
    return Decimal(str(float(value)))


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, start=_DECIMAL_ZERO) / len(values) if values else _DECIMAL_ZERO


def _median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return _DECIMAL_ZERO
    return _decimal(statistics.median(float(value) for value in values))


def _sample_std(values: Sequence[float]) -> float | None:
    return statistics.stdev(values) if len(values) >= 2 else None


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return _DECIMAL_ZERO
    return numerator / denominator * _DECIMAL_HUNDRED


def _time_key(time_ns: int, mode: str) -> str:
    timestamp = datetime.fromtimestamp(time_ns / 1_000_000_000, tz=UTC)
    if mode == "day":
        return timestamp.strftime("%Y-%m-%d")
    if mode == "month":
        return timestamp.strftime("%Y-%m")
    if mode == "year":
        return timestamp.strftime("%Y")
    raise ValueError(f"unsupported period mode: {mode}")


def _daily_points(
    equity_curve: Sequence[EquityCurvePoint],
    initial_balance: Decimal,
) -> tuple[PeriodReturnPoint, ...]:
    daily_last: dict[str, EquityCurvePoint] = {}
    for point in equity_curve:
        daily_last[_time_key(point.time_ns, "day")] = point
    previous = initial_balance
    result: list[PeriodReturnPoint] = []
    for period, point in sorted(daily_last.items()):
        pnl = point.equity - previous
        result.append(
            PeriodReturnPoint(
                time_ns=point.time_ns,
                period=period,
                equity=point.equity,
                pnl=pnl,
                return_percent=_percent(pnl, previous),
            )
        )
        previous = point.equity
    return tuple(result)


def _annualized_ratios(
    returns_percent: Sequence[Decimal],
    config: AnalyticsConfig,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if len(returns_percent) < 2:
        return None, None, None
    values = [float(value / _DECIMAL_HUNDRED) for value in returns_percent]
    mean_return = statistics.mean(values)
    standard_deviation = _sample_std(values)
    annualization = math.sqrt(config.annualization_days)
    risk_free_daily = float(config.risk_free_rate_percent / _DECIMAL_HUNDRED) / float(
        config.annualization_days
    )
    sharpe = None
    volatility = None
    if standard_deviation is not None and standard_deviation > 0:
        sharpe = (mean_return - risk_free_daily) / standard_deviation * annualization
        volatility = standard_deviation * annualization * 100
    downside = [min(0.0, value - risk_free_daily) for value in values]
    downside_deviation = math.sqrt(sum(value * value for value in downside) / len(downside))
    sortino = None
    if downside_deviation > 0:
        sortino = (mean_return - risk_free_daily) / downside_deviation * annualization
    return (
        _decimal(sharpe) if sharpe is not None else None,
        _decimal(sortino) if sortino is not None else None,
        _decimal(volatility) if volatility is not None else None,
    )


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _drawdown_episodes(
    equity_curve: Sequence[EquityCurvePoint],
) -> tuple[DrawdownEpisode, ...]:
    if not equity_curve:
        return ()
    episodes: list[DrawdownEpisode] = []
    peak = equity_curve[0].equity
    peak_time = equity_curve[0].time_ns
    active_start: int | None = None
    trough_time = equity_curve[0].time_ns
    max_amount = _DECIMAL_ZERO
    max_percent = _DECIMAL_ZERO
    for point in equity_curve:
        if point.equity >= peak:
            if active_start is not None:
                episodes.append(
                    DrawdownEpisode(
                        start_time_ns=active_start,
                        trough_time_ns=trough_time,
                        recovery_time_ns=point.time_ns,
                        max_drawdown_amount=max_amount,
                        max_drawdown_percent=max_percent,
                        duration_minutes=Decimal(point.time_ns - active_start) / _NS_PER_MINUTE,
                        recovery_minutes=Decimal(point.time_ns - trough_time) / _NS_PER_MINUTE,
                    )
                )
                active_start = None
                max_amount = _DECIMAL_ZERO
                max_percent = _DECIMAL_ZERO
            peak = point.equity
            peak_time = point.time_ns
            continue
        amount = peak - point.equity
        percent = _percent(amount, peak)
        if active_start is None:
            active_start = peak_time
            trough_time = point.time_ns
        if amount > max_amount:
            max_amount = amount
            max_percent = percent
            trough_time = point.time_ns
    if active_start is not None:
        last_time = equity_curve[-1].time_ns
        episodes.append(
            DrawdownEpisode(
                start_time_ns=active_start,
                trough_time_ns=trough_time,
                recovery_time_ns=None,
                max_drawdown_amount=max_amount,
                max_drawdown_percent=max_percent,
                duration_minutes=Decimal(last_time - active_start) / _NS_PER_MINUTE,
                recovery_minutes=None,
            )
        )
    return tuple(episodes)


def _rolling_metrics(
    daily_returns: Sequence[PeriodReturnPoint],
    config: AnalyticsConfig,
) -> tuple[RollingMetricPoint, ...]:
    result: list[RollingMetricPoint] = []
    window = config.rolling_window_days
    for index, point in enumerate(daily_returns):
        values = tuple(
            item.return_percent for item in daily_returns[max(0, index - window + 1) : index + 1]
        )
        sharpe, sortino, volatility = _annualized_ratios(values, config)
        equities = [item.equity for item in daily_returns[max(0, index - window + 1) : index + 1]]
        peak = max(equities) if equities else point.equity
        drawdown = _percent(peak - point.equity, peak) if peak > 0 else _DECIMAL_ZERO
        result.append(
            RollingMetricPoint(
                time_ns=point.time_ns,
                sharpe_ratio=sharpe,
                sortino_ratio=sortino,
                annualized_volatility_percent=volatility,
                rolling_drawdown_percent=drawdown,
            )
        )
    return tuple(result)


def _periodic_performance(
    equity_curve: Sequence[EquityCurvePoint],
    trades: Sequence[Trade],
    initial_balance: Decimal,
    mode: str,
) -> tuple[PeriodicPerformance, ...]:
    grouped_points: dict[str, list[EquityCurvePoint]] = defaultdict(list)
    grouped_trades: dict[str, list[Trade]] = defaultdict(list)
    for point in equity_curve:
        grouped_points[_time_key(point.time_ns, mode)].append(point)
    for trade in trades:
        grouped_trades[_time_key(trade.exit_time_ns, mode)].append(trade)
    previous_equity = initial_balance
    result: list[PeriodicPerformance] = []
    for period in sorted(grouped_points):
        points = grouped_points[period]
        period_trades = grouped_trades.get(period, [])
        opening = previous_equity
        closing = points[-1].equity
        peak = opening
        maximum_drawdown = _DECIMAL_ZERO
        for point in points:
            peak = max(peak, point.equity)
            if peak > 0:
                maximum_drawdown = max(maximum_drawdown, _percent(peak - point.equity, peak))
        wins = sum(trade.net_pnl > 0 for trade in period_trades)
        losses = sum(trade.net_pnl < 0 for trade in period_trades)
        result.append(
            PeriodicPerformance(
                period=period,
                start_time_ns=points[0].time_ns,
                end_time_ns=points[-1].time_ns,
                opening_equity=opening,
                closing_equity=closing,
                net_pnl=sum((trade.net_pnl for trade in period_trades), start=_DECIMAL_ZERO),
                return_percent=_percent(closing - opening, opening),
                max_drawdown_percent=maximum_drawdown,
                trade_count=len(period_trades),
                winning_trades=wins,
                losing_trades=losses,
                win_rate_percent=(
                    Decimal(wins * 100) / len(period_trades) if period_trades else _DECIMAL_ZERO
                ),
            )
        )
        previous_equity = closing
    return tuple(result)


def _breakdown_row(key: str, label: str, trades: Sequence[Trade]) -> BreakdownRow:
    wins = tuple(trade for trade in trades if trade.net_pnl > 0)
    losses = tuple(trade for trade in trades if trade.net_pnl < 0)
    gross_profit = sum((trade.net_pnl for trade in wins), start=_DECIMAL_ZERO)
    gross_loss = -sum((trade.net_pnl for trade in losses), start=_DECIMAL_ZERO)
    r_values = tuple(
        trade.realized_r_multiple for trade in trades if trade.realized_r_multiple is not None
    )
    durations = tuple(
        Decimal(trade.exit_time_ns - trade.entry_time_ns) / _NS_PER_MINUTE for trade in trades
    )
    return BreakdownRow(
        key=key,
        label=label,
        trade_count=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate_percent=Decimal(len(wins) * 100) / len(trades) if trades else _DECIMAL_ZERO,
        net_pnl=sum((trade.net_pnl for trade in trades), start=_DECIMAL_ZERO),
        average_pnl=_mean(tuple(trade.net_pnl for trade in trades)),
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else None,
        average_r_multiple=_mean(r_values) if r_values else None,
        average_holding_minutes=_mean(durations),
    )


def _breakdown[KeyT: Hashable](
    trades: Sequence[Trade],
    key_function: Callable[[Trade], KeyT],
    label_function: Callable[[KeyT], str] | None = None,
) -> tuple[BreakdownRow, ...]:
    grouped: dict[KeyT, list[Trade]] = defaultdict(list)
    for trade in trades:
        grouped[key_function(trade)].append(trade)
    rows = [
        _breakdown_row(
            str(key),
            label_function(key) if label_function is not None else str(key),
            grouped[key],
        )
        for key in sorted(grouped, key=lambda value: str(value))
    ]
    return tuple(rows)


def _distribution(
    values: Sequence[Decimal], bucket_count: int = 10
) -> tuple[DistributionBucket, ...]:
    if not values:
        return ()
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return (
            DistributionBucket(
                label=f"{minimum}",
                lower_bound=minimum,
                upper_bound=maximum,
                count=len(values),
                percentage=_DECIMAL_HUNDRED,
            ),
        )
    width = (maximum - minimum) / bucket_count
    counts = [0 for _ in range(bucket_count)]
    for value in values:
        index = min(bucket_count - 1, int((value - minimum) / width))
        counts[index] += 1
    result: list[DistributionBucket] = []
    for index, count in enumerate(counts):
        lower = minimum + width * index
        upper = maximum if index == bucket_count - 1 else minimum + width * (index + 1)
        result.append(
            DistributionBucket(
                label=f"{lower:.2f} to {upper:.2f}",
                lower_bound=lower,
                upper_bound=upper,
                count=count,
                percentage=Decimal(count * 100) / len(values),
            )
        )
    return tuple(result)


def _merged_exposure_minutes(trades: Sequence[Trade]) -> Decimal:
    intervals = sorted((trade.entry_time_ns, trade.exit_time_ns) for trade in trades)
    if not intervals:
        return _DECIMAL_ZERO
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
    return sum(
        (Decimal(end - start) / _NS_PER_MINUTE for start, end in merged),
        start=_DECIMAL_ZERO,
    )


def _consecutive(trades: Sequence[Trade]) -> tuple[int, int]:
    maximum_wins = 0
    maximum_losses = 0
    current_wins = 0
    current_losses = 0
    for trade in sorted(trades, key=lambda item: (item.exit_time_ns, item.trade_id)):
        if trade.net_pnl > 0:
            current_wins += 1
            current_losses = 0
        elif trade.net_pnl < 0:
            current_losses += 1
            current_wins = 0
        else:
            current_wins = 0
            current_losses = 0
        maximum_wins = max(maximum_wins, current_wins)
        maximum_losses = max(maximum_losses, current_losses)
    return maximum_wins, maximum_losses


def _performance(
    trades: Sequence[Trade],
    initial_balance: Decimal,
    final_balance: Decimal,
    final_equity: Decimal,
    start_time_ns: int,
    end_time_ns: int,
    config: AnalyticsConfig,
) -> PerformanceMetrics:
    wins = tuple(trade for trade in trades if trade.net_pnl > 0)
    losses = tuple(trade for trade in trades if trade.net_pnl < 0)
    pnl_values = tuple(trade.net_pnl for trade in trades)
    gross_profit = sum((trade.net_pnl for trade in wins), start=_DECIMAL_ZERO)
    gross_loss = -sum((trade.net_pnl for trade in losses), start=_DECIMAL_ZERO)
    gross_pnl = sum((trade.gross_pnl for trade in trades), start=_DECIMAL_ZERO)
    net_pnl = final_balance - initial_balance
    r_values = tuple(
        trade.realized_r_multiple for trade in trades if trade.realized_r_multiple is not None
    )
    duration_days = Decimal(end_time_ns - start_time_ns) / _NS_PER_DAY
    cagr = None
    if (
        duration_days >= config.minimum_annualization_days
        and initial_balance > 0
        and final_equity > 0
    ):
        years = float(duration_days / Decimal("365.2425"))
        cagr = _decimal(((float(final_equity / initial_balance) ** (1 / years)) - 1) * 100)
    payoff = None
    average_win = _mean(tuple(trade.net_pnl for trade in wins)) if wins else None
    average_loss = _mean(tuple(trade.net_pnl for trade in losses)) if losses else None
    if average_win is not None and average_loss is not None and average_loss != 0:
        payoff = average_win / abs(average_loss)
    sqn = None
    if len(r_values) >= 2:
        r_float = [float(value) for value in r_values]
        deviation = statistics.stdev(r_float)
        if deviation > 0:
            sqn = _decimal(math.sqrt(len(r_values)) * statistics.mean(r_float) / deviation)
    return PerformanceMetrics(
        initial_balance=initial_balance,
        final_balance=final_balance,
        final_equity=final_equity,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        total_return_percent=_percent(final_equity - initial_balance, initial_balance),
        cagr_percent=cagr,
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else None,
        expectancy=_mean(pnl_values),
        average_trade=_mean(pnl_values),
        median_trade=_median(pnl_values),
        average_win=average_win,
        average_loss=average_loss,
        payoff_ratio=payoff,
        best_trade=max(pnl_values) if pnl_values else None,
        worst_trade=min(pnl_values) if pnl_values else None,
        average_r_multiple=_mean(r_values) if r_values else None,
        median_r_multiple=_median(r_values) if r_values else None,
        system_quality_number=sqn,
    )


def _risk(
    equity_curve: Sequence[EquityCurvePoint],
    daily_returns: Sequence[PeriodReturnPoint],
    episodes: Sequence[DrawdownEpisode],
    performance: PerformanceMetrics,
    config: AnalyticsConfig,
) -> RiskMetrics:
    returns = tuple(point.return_percent for point in daily_returns)
    sharpe, sortino, volatility = _annualized_ratios(returns, config)
    drawdowns = tuple(point.drawdown_percent for point in equity_curve)
    max_amount = max((point.drawdown_amount for point in equity_curve), default=_DECIMAL_ZERO)
    max_percent = max(drawdowns, default=_DECIMAL_ZERO)
    max_duration = max((episode.duration_minutes for episode in episodes), default=_DECIMAL_ZERO)
    recovered = tuple(
        episode.recovery_minutes for episode in episodes if episode.recovery_minutes is not None
    )
    maximum_recovery = max(recovered) if recovered else None
    ulcer = (
        _decimal(math.sqrt(statistics.mean(float(value) ** 2 for value in drawdowns)))
        if drawdowns
        else _DECIMAL_ZERO
    )
    return_values = [float(value) for value in returns]
    confidence_tail = 1 - float(config.confidence_level)
    quantile = _quantile(return_values, confidence_tail)
    var = max(0.0, -quantile) if quantile is not None else None
    tail = [value for value in return_values if quantile is not None and value <= quantile]
    cvar = max(0.0, -statistics.mean(tail)) if tail else None
    calmar = None
    if performance.cagr_percent is not None and max_percent > 0:
        calmar = performance.cagr_percent / max_percent
    recovery_factor = performance.net_pnl / max_amount if max_amount > 0 else None
    return RiskMetrics(
        max_drawdown_amount=max_amount,
        max_drawdown_percent=max_percent,
        max_drawdown_duration_minutes=max_duration,
        max_recovery_duration_minutes=maximum_recovery,
        average_drawdown_percent=_mean(drawdowns),
        annualized_volatility_percent=volatility,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        recovery_factor=recovery_factor,
        ulcer_index=ulcer,
        value_at_risk_percent=_decimal(var) if var is not None else None,
        conditional_value_at_risk_percent=_decimal(cvar) if cvar is not None else None,
        best_day_return_percent=max(returns) if returns else None,
        worst_day_return_percent=min(returns) if returns else None,
    )


def _trade_behavior(
    trades: Sequence[Trade],
    start_time_ns: int,
    end_time_ns: int,
) -> TradeBehaviorMetrics:
    wins = tuple(trade for trade in trades if trade.net_pnl > 0)
    losses = tuple(trade for trade in trades if trade.net_pnl < 0)
    breakeven = tuple(trade for trade in trades if trade.net_pnl == 0)
    durations = tuple(
        Decimal(trade.exit_time_ns - trade.entry_time_ns) / _NS_PER_MINUTE for trade in trades
    )
    max_wins, max_losses = _consecutive(trades)
    total_minutes = Decimal(max(0, end_time_ns - start_time_ns)) / _NS_PER_MINUTE
    exposure_minutes = _merged_exposure_minutes(trades)
    mfe_capture_values = tuple(
        max(_DECIMAL_ZERO, trade.gross_pnl) / trade.mfe * _DECIMAL_HUNDRED
        for trade in trades
        if trade.mfe > 0 and trade.gross_pnl > 0
    )
    return TradeBehaviorMetrics(
        total_trades=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        breakeven_trades=len(breakeven),
        long_trades=sum(trade.side.value == "long" for trade in trades),
        short_trades=sum(trade.side.value == "short" for trade in trades),
        win_rate_percent=Decimal(len(wins) * 100) / len(trades) if trades else _DECIMAL_ZERO,
        loss_rate_percent=Decimal(len(losses) * 100) / len(trades) if trades else _DECIMAL_ZERO,
        average_holding_minutes=_mean(durations),
        median_holding_minutes=_median(durations),
        longest_holding_minutes=max(durations, default=_DECIMAL_ZERO),
        max_consecutive_wins=max_wins,
        max_consecutive_losses=max_losses,
        time_in_market_percent=(
            min(_DECIMAL_HUNDRED, exposure_minutes / total_minutes * _DECIMAL_HUNDRED)
            if total_minutes > 0
            else _DECIMAL_ZERO
        ),
        ambiguous_trade_count=sum(trade.intrabar_ambiguous for trade in trades),
        average_mae=_mean(tuple(trade.mae for trade in trades)),
        average_mfe=_mean(tuple(trade.mfe for trade in trades)),
        average_mfe_capture_percent=_mean(mfe_capture_values) if mfe_capture_values else None,
    )


def _costs(trades: Sequence[Trade], gross_profit: Decimal) -> ExecutionCostMetrics:
    commission = sum((trade.commission for trade in trades), start=_DECIMAL_ZERO)
    spread = sum((trade.spread_cost for trade in trades), start=_DECIMAL_ZERO)
    slippage = sum((trade.slippage_cost for trade in trades), start=_DECIMAL_ZERO)
    swap = sum((trade.swap for trade in trades), start=_DECIMAL_ZERO)
    total = commission + spread + slippage - swap
    denominator = commission + spread + slippage
    return ExecutionCostMetrics(
        commission=commission,
        spread_cost=spread,
        slippage_cost=slippage,
        swap=swap,
        total_cost=total,
        average_cost_per_trade=total / len(trades) if trades else _DECIMAL_ZERO,
        cost_to_gross_profit_percent=_percent(total, gross_profit) if gross_profit > 0 else None,
        commission_share_percent=_percent(commission, denominator),
        spread_share_percent=_percent(spread, denominator),
        slippage_share_percent=_percent(slippage, denominator),
    )


class AnalyticsEngine:
    def calculate(
        self,
        *,
        run_id: str,
        currency: CurrencyCode,
        initial_balance: Decimal,
        start_time_ns: int,
        end_time_ns: int,
        trades: Iterable[Trade],
        equity_curve: Iterable[EquityCurvePoint],
        config: AnalyticsConfig | None = None,
    ) -> AnalyticsReport:
        settings = config or AnalyticsConfig()
        ordered_trades = tuple(
            sorted(trades, key=lambda trade: (trade.exit_time_ns, trade.trade_id))
        )
        ordered_equity = tuple(sorted(equity_curve, key=lambda point: point.time_ns))
        if end_time_ns < start_time_ns:
            raise ValueError("end_time_ns must not precede start_time_ns")
        final_equity = ordered_equity[-1].equity if ordered_equity else initial_balance
        final_balance = ordered_equity[-1].balance if ordered_equity else initial_balance
        performance = _performance(
            ordered_trades,
            initial_balance,
            final_balance,
            final_equity,
            start_time_ns,
            end_time_ns,
            settings,
        )
        daily = _daily_points(ordered_equity, initial_balance)
        episodes = _drawdown_episodes(ordered_equity)
        payload = {
            "run_id": run_id,
            "start_time_ns": start_time_ns,
            "end_time_ns": end_time_ns,
            "trade_ids": [trade.trade_id for trade in ordered_trades],
            "equity_count": len(ordered_equity),
            "config": settings.model_dump(mode="json"),
        }
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return AnalyticsReport(
            report_id=f"analytics_{digest[:24]}",
            run_id=run_id,
            generated_at=datetime.fromtimestamp(end_time_ns / 1_000_000_000, tz=UTC),
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            currency=currency,
            config=settings,
            performance=performance,
            risk=_risk(ordered_equity, daily, episodes, performance, settings),
            trades=_trade_behavior(ordered_trades, start_time_ns, end_time_ns),
            costs=_costs(ordered_trades, performance.gross_profit),
            equity_curve=ordered_equity,
            daily_returns=daily,
            rolling_metrics=_rolling_metrics(daily, settings),
            monthly_performance=_periodic_performance(
                ordered_equity, ordered_trades, initial_balance, "month"
            ),
            yearly_performance=_periodic_performance(
                ordered_equity, ordered_trades, initial_balance, "year"
            ),
            drawdown_episodes=episodes,
            side_breakdown=_breakdown(
                ordered_trades,
                lambda trade: trade.side.value,
                lambda value: str(value).title(),
            ),
            symbol_breakdown=_breakdown(ordered_trades, lambda trade: trade.symbol),
            exit_reason_breakdown=_breakdown(ordered_trades, lambda trade: trade.exit_reason),
            weekday_breakdown=_breakdown(
                ordered_trades,
                lambda trade: datetime.fromtimestamp(
                    trade.exit_time_ns / 1_000_000_000, tz=UTC
                ).weekday(),
                lambda value: ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[int(value)],
            ),
            hour_breakdown=_breakdown(
                ordered_trades,
                lambda trade: (
                    datetime.fromtimestamp(trade.exit_time_ns / 1_000_000_000, tz=UTC).hour
                ),
                lambda value: f"{int(value):02d}:00 UTC",
            ),
            pnl_distribution=_distribution(tuple(trade.net_pnl for trade in ordered_trades)),
            r_multiple_distribution=_distribution(
                tuple(
                    trade.realized_r_multiple
                    for trade in ordered_trades
                    if trade.realized_r_multiple is not None
                )
            ),
            duration_distribution=_distribution(
                tuple(
                    Decimal(trade.exit_time_ns - trade.entry_time_ns) / _NS_PER_MINUTE
                    for trade in ordered_trades
                )
            ),
        )
