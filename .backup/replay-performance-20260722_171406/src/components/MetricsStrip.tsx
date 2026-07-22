import { memo } from "react";
import {
  Activity,
  ArrowDownRight,
  BadgeDollarSign,
  Percent,
  Scale,
  ShieldCheck,
  Sigma
} from "lucide-react";
import { formatMoney, formatNumber, formatPercent, signedClass } from "../lib/format";
import type { AccountSnapshot, ReplayMetrics } from "../lib/types";

interface Props {
  metrics: ReplayMetrics;
  account: AccountSnapshot;
}

export const MetricsStrip = memo(function MetricsStrip({ metrics, account }: Props) {
  const equityDelta = Number(account.equity) - Number(metrics.initial_balance);
  const cards = [
    {
      label: "Equity",
      value: formatMoney(account.equity, account.currency),
      detail: `${equityDelta >= 0 ? "+" : ""}${formatMoney(equityDelta, account.currency)}`,
      icon: BadgeDollarSign,
      tone: signedClass(equityDelta)
    },
    {
      label: "Net P&L",
      value: formatMoney(metrics.net_pnl, account.currency),
      detail: `${metrics.total_trades} completed trades`,
      icon: Activity,
      tone: signedClass(metrics.net_pnl)
    },
    {
      label: "Win rate",
      value: formatPercent(metrics.win_rate),
      detail: `${metrics.winning_trades}W / ${metrics.losing_trades}L`,
      icon: Percent,
      tone: "neutral" as const
    },
    {
      label: "Profit factor",
      value: metrics.profit_factor ? formatNumber(metrics.profit_factor) : "—",
      detail: `${metrics.long_trades} long · ${metrics.short_trades} short`,
      icon: Scale,
      tone: "neutral" as const
    },
    {
      label: "Average R",
      value: metrics.average_r_multiple ? `${formatNumber(metrics.average_r_multiple)}R` : "—",
      detail: `Gross ${formatMoney(metrics.gross_pnl, account.currency)}`,
      icon: Sigma,
      tone: signedClass(metrics.average_r_multiple ?? 0)
    },
    {
      label: "Max drawdown",
      value: formatPercent(metrics.max_drawdown_percent),
      detail: formatMoney(metrics.max_drawdown_amount, account.currency),
      icon: ArrowDownRight,
      tone: "negative" as const
    },
    {
      label: "Free margin",
      value: formatMoney(account.free_margin, account.currency),
      detail: account.margin_level_percent ? `${formatNumber(account.margin_level_percent)}% margin level` : "No used margin",
      icon: ShieldCheck,
      tone: "neutral" as const
    }
  ];

  return (
    <section className="metrics-strip" aria-label="Run metrics">
      {cards.map(card => (
        <article key={card.label} className="metric-card">
          <div className={`metric-icon ${card.tone}`}><card.icon size={15} /></div>
          <div className="metric-copy">
            <span>{card.label}</span>
            <strong className={card.tone}>{card.value}</strong>
            <small>{card.detail}</small>
          </div>
        </article>
      ))}
    </section>
  );
});
