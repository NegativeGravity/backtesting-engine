import { memo, useMemo } from "react";
import {
  Activity,
  BarChart3,
  Clock3,
  Coins,
  Gauge,
  Layers3,
  ShieldAlert,
  Target,
  TrendingDown,
  TrendingUp
} from "lucide-react";
import { downsampleEnvelope, finiteExtent } from "../lib/downsample";
import { formatDateTime, formatMoney, formatNumber, formatPercent, signedClass } from "../lib/format";
import type {
  AnalyticsReport,
  BreakdownRow,
  DistributionBucket,
  EquityCurvePoint,
  PeriodicPerformance
} from "../lib/types";

interface Props {
  report: AnalyticsReport;
  scope: "full" | "cursor";
  loading: boolean;
  onScopeChange: (scope: "full" | "cursor") => void;
}

export const AnalyticsDashboard = memo(function AnalyticsDashboard({ report, scope, loading, onScopeChange }: Props) {
  const { performance, risk, trades, costs } = report;
  return (
    <main className={`analytics-dashboard ${loading ? "is-loading" : ""}`}>
      <header className="analytics-heading">
        <div>
          <span className="eyebrow">Advanced strategy analytics</span>
          <h1>Performance Intelligence</h1>
          <p>
            {formatDateTime(report.start_time_ns)} — {formatDateTime(report.end_time_ns)} · UTC
          </p>
        </div>
        <div className="analytics-scope">
          <button className={scope === "full" ? "active" : ""} onClick={() => onScopeChange("full")}>Full run</button>
          <button className={scope === "cursor" ? "active" : ""} onClick={() => onScopeChange("cursor")}>Replay cursor</button>
          {loading ? <span className="analytics-loading"><Activity size={13} /> Updating</span> : null}
        </div>
      </header>

      <section className="analytics-kpis">
        <Kpi icon={TrendingUp} label="Net P&L" value={formatMoney(performance.net_pnl, report.currency)} tone={signedClass(performance.net_pnl)} detail={`${formatPercent(performance.total_return_percent)} return`} />
        <Kpi icon={TrendingDown} label="Max drawdown" value={formatPercent(risk.max_drawdown_percent)} tone="negative" detail={formatMoney(risk.max_drawdown_amount, report.currency)} />
        <Kpi icon={Gauge} label="Sharpe ratio" value={metric(risk.sharpe_ratio)} detail={`Sortino ${metric(risk.sortino_ratio)}`} />
        <Kpi icon={Target} label="Profit factor" value={metric(performance.profit_factor)} detail={`Payoff ${metric(performance.payoff_ratio)}`} />
        <Kpi icon={BarChart3} label="Win rate" value={formatPercent(trades.win_rate_percent)} detail={`${trades.winning_trades}W / ${trades.losing_trades}L`} />
        <Kpi icon={Clock3} label="Market exposure" value={formatPercent(trades.time_in_market_percent)} detail={`${formatNumber(trades.average_holding_minutes)} min avg`} />
      </section>

      <section className="analytics-chart-grid">
        <article className="analytics-card chart-card wide">
          <CardTitle icon={TrendingUp} title="Equity curve" subtitle={`${report.equity_curve.length.toLocaleString()} execution points`} />
          <EquityChart points={report.equity_curve} currency={report.currency} />
        </article>
        <article className="analytics-card chart-card">
          <CardTitle icon={ShieldAlert} title="Drawdown" subtitle="Peak-to-trough equity decline" />
          <DrawdownChart points={report.equity_curve} />
        </article>
      </section>

      <section className="analytics-card monthly-card">
        <CardTitle icon={Layers3} title="Monthly performance" subtitle="Realized P&L, return, trades and drawdown" />
        <MonthlyMatrix rows={report.monthly_performance} currency={report.currency} />
      </section>

      <section className="analytics-detail-grid">
        <MetricGroup title="Performance" icon={TrendingUp} items={[
          ["Gross profit", formatMoney(performance.gross_profit, report.currency), "positive"],
          ["Gross loss", formatMoney(performance.gross_loss, report.currency), "negative"],
          ["Expectancy", formatMoney(performance.expectancy, report.currency), signedClass(performance.expectancy)],
          ["Average trade", formatMoney(performance.average_trade, report.currency), signedClass(performance.average_trade)],
          ["Average R", metric(performance.average_r_multiple, "R")],
          ["SQN", metric(performance.system_quality_number)],
          ["CAGR", optionalPercent(performance.cagr_percent)],
          ["Best / worst", `${nullableMoney(performance.best_trade, report.currency)} / ${nullableMoney(performance.worst_trade, report.currency)}`]
        ]} />
        <MetricGroup title="Risk" icon={ShieldAlert} items={[
          ["Volatility", optionalPercent(risk.annualized_volatility_percent)],
          ["Calmar", metric(risk.calmar_ratio)],
          ["Recovery factor", metric(risk.recovery_factor)],
          ["Ulcer index", metric(risk.ulcer_index)],
          ["VaR", optionalPercent(risk.value_at_risk_percent)],
          ["CVaR", optionalPercent(risk.conditional_value_at_risk_percent)],
          ["DD duration", duration(risk.max_drawdown_duration_minutes)],
          ["Recovery time", duration(risk.max_recovery_duration_minutes)]
        ]} />
        <MetricGroup title="Trade behavior" icon={Target} items={[
          ["Total trades", String(trades.total_trades)],
          ["Long / short", `${trades.long_trades} / ${trades.short_trades}`],
          ["Consecutive W / L", `${trades.max_consecutive_wins} / ${trades.max_consecutive_losses}`],
          ["Median duration", duration(trades.median_holding_minutes)],
          ["Longest trade", duration(trades.longest_holding_minutes)],
          ["Average MAE", formatMoney(trades.average_mae, report.currency)],
          ["Average MFE", formatMoney(trades.average_mfe, report.currency)],
          ["Ambiguous bars", String(trades.ambiguous_trade_count)]
        ]} />
        <MetricGroup title="Execution costs" icon={Coins} items={[
          ["Total cost", formatMoney(costs.total_cost, report.currency), "negative"],
          ["Commission", formatMoney(costs.commission, report.currency)],
          ["Spread", formatMoney(costs.spread_cost, report.currency)],
          ["Slippage", formatMoney(costs.slippage_cost, report.currency)],
          ["Swap", formatMoney(costs.swap, report.currency), signedClass(costs.swap)],
          ["Cost / trade", formatMoney(costs.average_cost_per_trade, report.currency)],
          ["Cost / gross profit", optionalPercent(costs.cost_to_gross_profit_percent)],
          ["Commission / spread", `${formatPercent(costs.commission_share_percent, 1)} / ${formatPercent(costs.spread_share_percent, 1)}`]
        ]} />
      </section>

      <section className="analytics-breakdown-grid">
        <BreakdownTable title="Side performance" rows={report.side_breakdown} currency={report.currency} />
        <BreakdownTable title="Exit reasons" rows={report.exit_reason_breakdown} currency={report.currency} />
        <BreakdownTable title="Weekday" rows={report.weekday_breakdown} currency={report.currency} />
        <BreakdownTable title="Hour of day" rows={report.hour_breakdown} currency={report.currency} />
      </section>

      <section className="analytics-distribution-grid">
        <DistributionChart title="Net P&L distribution" buckets={report.pnl_distribution} />
        <DistributionChart title="R-multiple distribution" buckets={report.r_multiple_distribution} />
        <DistributionChart title="Holding duration distribution" buckets={report.duration_distribution} />
      </section>

      <section className="analytics-card drawdown-table-card">
        <CardTitle icon={TrendingDown} title="Drawdown episodes" subtitle="Largest peak-to-recovery periods" />
        <div className="table-scroll analytics-table-scroll">
          <table>
            <thead><tr><th>Start</th><th>Trough</th><th>Recovery</th><th>Drawdown</th><th>Amount</th><th>Duration</th></tr></thead>
            <tbody>
              {report.drawdown_episodes.slice().sort((a, b) => Number(b.max_drawdown_percent) - Number(a.max_drawdown_percent)).slice(0, 20).map((episode, index) => (
                <tr key={`${episode.start_time_ns}-${index}`}>
                  <td>{formatDateTime(episode.start_time_ns)}</td>
                  <td>{formatDateTime(episode.trough_time_ns)}</td>
                  <td>{episode.recovery_time_ns ? formatDateTime(episode.recovery_time_ns) : "Open"}</td>
                  <td className="negative">-{formatPercent(episode.max_drawdown_percent)}</td>
                  <td className="negative">-{formatMoney(episode.max_drawdown_amount, report.currency)}</td>
                  <td>{duration(episode.duration_minutes)}</td>
                </tr>
              ))}
              {report.drawdown_episodes.length === 0 ? <tr><td colSpan={6} className="analytics-empty">No drawdown episodes</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
});

function Kpi({ icon: Icon, label, value, detail, tone = "neutral" }: { icon: typeof TrendingUp; label: string; value: string; detail: string; tone?: string }) {
  return <article className="analytics-kpi"><div className={`kpi-icon ${tone}`}><Icon size={17} /></div><div><span>{label}</span><strong className={tone}>{value}</strong><small>{detail}</small></div></article>;
}

function CardTitle({ icon: Icon, title, subtitle }: { icon: typeof TrendingUp; title: string; subtitle: string }) {
  return <header className="analytics-card-title"><div><Icon size={15} /><strong>{title}</strong></div><span>{subtitle}</span></header>;
}

function MetricGroup({ title, icon: Icon, items }: { title: string; icon: typeof TrendingUp; items: Array<[string, string, string?]> }) {
  return <article className="analytics-card metric-group"><CardTitle icon={Icon} title={title} subtitle="" /><dl>{items.map(([label, value, tone]) => <div key={label}><dt>{label}</dt><dd className={tone ?? ""}>{value}</dd></div>)}</dl></article>;
}

function EquityChart({ points, currency }: { points: EquityCurvePoint[]; currency: string }) {
  const { values, extent, last } = useMemo(() => {
    const rawValues = points.map(point => Number(point.equity));
    return {
      values: downsampleEnvelope(rawValues, 1_400),
      extent: finiteExtent(rawValues),
      last: rawValues.at(-1) ?? 0
    };
  }, [points]);
  if (values.length < 2 || extent === null) return <ChartEmpty />;
  const path = linePath(values, 720, 190, 10, extent.minimum, extent.maximum);
  return <div className="svg-chart"><svg viewBox="0 0 720 190" preserveAspectRatio="none"><defs><linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity="0.32"/><stop offset="100%" stopColor="var(--accent)" stopOpacity="0"/></linearGradient></defs><path className="chart-area" d={`${path} L 710 180 L 10 180 Z`} fill="url(#equityFill)"/><path className="chart-line" d={path}/></svg><div className="chart-range"><span>{formatMoney(extent.minimum, currency)}</span><strong>{formatMoney(last, currency)}</strong><span>{formatMoney(extent.maximum, currency)}</span></div></div>;
}

function DrawdownChart({ points }: { points: EquityCurvePoint[] }) {
  const { values, maximum } = useMemo(() => {
    const rawValues = points.map(point => Number(point.drawdown_percent));
    const extent = finiteExtent(rawValues);
    return {
      values: downsampleEnvelope(rawValues, 900),
      maximum: extent?.maximum ?? 0
    };
  }, [points]);
  if (values.length < 2) return <ChartEmpty />;
  const path = linePath(values, 360, 190, 10, 0, maximum, true);
  return <div className="svg-chart drawdown-chart"><svg viewBox="0 0 360 190" preserveAspectRatio="none"><defs><linearGradient id="drawdownFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--negative)" stopOpacity="0.08"/><stop offset="100%" stopColor="var(--negative)" stopOpacity="0.34"/></linearGradient></defs><path className="chart-area" d={`${path} L 350 180 L 10 180 Z`} fill="url(#drawdownFill)"/><path className="chart-line negative-line" d={path}/></svg><div className="chart-range"><span>0%</span><strong className="negative">-{formatPercent(maximum)}</strong><span>Max</span></div></div>;
}

function linePath(values: number[], width: number, height: number, padding: number, minimum: number, maximum: number, invert = false): string {
  const span = Math.max(1e-9, maximum - minimum);
  return values.map((value, index) => {
    const x = padding + (index / Math.max(1, values.length - 1)) * (width - padding * 2);
    const normalized = (value - minimum) / span;
    const y = invert ? padding + normalized * (height - padding * 2) : height - padding - normalized * (height - padding * 2);
    return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(" ");
}

function MonthlyMatrix({ rows, currency }: { rows: PeriodicPerformance[]; currency: string }) {
  const years = new Map<number, Map<number, PeriodicPerformance>>();
  for (const row of rows) {
    const [yearValue, monthValue] = row.period.split("-");
    const year = Number(yearValue);
    const month = Number(monthValue) - 1;
    const months = years.get(year) ?? new Map<number, PeriodicPerformance>();
    months.set(month, row);
    years.set(year, months);
  }
  const magnitude = Math.max(1, ...rows.map(row => Math.abs(Number(row.return_percent))));
  return <div className="analytics-monthly-grid"><div className="monthly-corner">Year</div>{monthNames.map(month => <div key={month} className="analytics-month-header">{month}</div>)}{[...years.entries()].sort(([a], [b]) => a - b).flatMap(([year, values]) => [<div key={`${year}-label`} className="analytics-year">{year}</div>, ...monthNames.map((_, month) => { const row = values.get(month); if (!row) return <div key={`${year}-${month}`} className="analytics-month empty">—</div>; const intensity = Math.min(0.8, Math.abs(Number(row.return_percent)) / magnitude * 0.7 + 0.08); return <div key={`${year}-${month}`} className={`analytics-month ${signedClass(row.return_percent)}`} style={{ "--heat": intensity } as React.CSSProperties}><strong>{formatPercent(row.return_percent)}</strong><span>{formatMoney(row.net_pnl, currency)}</span><small>{row.trade_count} trades · DD {formatPercent(row.max_drawdown_percent, 1)}</small></div>; })])}{years.size === 0 ? <div className="analytics-empty matrix-empty">No monthly data</div> : null}</div>;
}

function BreakdownTable({ title, rows, currency }: { title: string; rows: BreakdownRow[]; currency: string }) {
  return <article className="analytics-card breakdown-card"><CardTitle icon={BarChart3} title={title} subtitle={`${rows.length} groups`} /><div className="table-scroll analytics-table-scroll"><table><thead><tr><th>Group</th><th>Trades</th><th>Win rate</th><th>Net P&L</th><th>PF</th><th>Avg R</th></tr></thead><tbody>{rows.map(row => <tr key={row.key}><td><strong>{row.label}</strong></td><td>{row.trade_count}</td><td>{formatPercent(row.win_rate_percent, 1)}</td><td className={signedClass(row.net_pnl)}>{formatMoney(row.net_pnl, currency)}</td><td>{metric(row.profit_factor)}</td><td>{metric(row.average_r_multiple, "R")}</td></tr>)}{rows.length === 0 ? <tr><td colSpan={6} className="analytics-empty">No trade data</td></tr> : null}</tbody></table></div></article>;
}

function DistributionChart({ title, buckets }: { title: string; buckets: DistributionBucket[] }) {
  const maximum = Math.max(1, ...buckets.map(bucket => bucket.count));
  return <article className="analytics-card distribution-card"><CardTitle icon={BarChart3} title={title} subtitle={`${buckets.reduce((sum, bucket) => sum + bucket.count, 0)} observations`} /><div className="distribution-bars">{buckets.map((bucket, index) => <div key={`${bucket.label}-${index}`} className="distribution-column" title={`${bucket.label}: ${bucket.count}`}><span>{bucket.count}</span><div style={{ height: `${Math.max(3, bucket.count / maximum * 100)}%` }} /><small>{compactRange(bucket.label)}</small></div>)}{buckets.length === 0 ? <div className="analytics-empty">Not enough observations</div> : null}</div></article>;
}

function ChartEmpty() { return <div className="analytics-empty chart-empty">Not enough data to render this chart</div>; }
function metric(value: string | null, suffix = ""): string { return value === null ? "—" : `${formatNumber(value)}${suffix}`; }
function optionalPercent(value: string | null): string { return value === null ? "—" : formatPercent(value); }
function nullableMoney(value: string | null, currency: string): string { return value === null ? "—" : formatMoney(value, currency); }
function duration(value: string | null): string { if (value === null) return "—"; const minutes = Number(value); if (minutes >= 1440) return `${formatNumber(minutes / 1440, 1)}d`; if (minutes >= 60) return `${formatNumber(minutes / 60, 1)}h`; return `${formatNumber(minutes, 1)}m`; }
function compactRange(value: string): string { return value.replace(" to ", "–").slice(0, 16); }
const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
