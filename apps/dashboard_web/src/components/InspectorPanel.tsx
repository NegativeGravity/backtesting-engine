import { memo, useMemo } from "react";
import {
  Layers3,
  ListTree,
  RadioTower,
  ShieldCheck,
  WalletCards
} from "lucide-react";
import { formatDateTime, formatMoney, formatNumber, formatPercent, signedClass } from "../lib/format";
import type {
  AccountSnapshot,
  OrderRecord,
  PositionRecord,
  ReplayTimelineItem
} from "../lib/types";

interface Props {
  account: AccountSnapshot;
  timeline: ReplayTimelineItem[];
  positions: PositionRecord[];
  orders: OrderRecord[];
  tickSize: number;
}

export const InspectorPanel = memo(function InspectorPanel({
  account,
  timeline,
  positions,
  orders,
  tickSize
}: Props) {
  const recent = useMemo(() => timeline.slice(-10).reverse(), [timeline]);
  const chartLayers = useMemo(() => recentChartLayers(timeline, 8), [timeline]);
  const activeOrderCount = useMemo(
    () => orders.reduce(
      (count, order) => count + (["accepted", "active", "partially_filled"].includes(order.status) ? 1 : 0),
      0
    ),
    [orders]
  );

  return (
    <aside className="inspector-panel">
      <section className="inspector-section">
        <div className="section-title"><WalletCards size={15} /><span>Account</span></div>
        <dl className="property-list">
          <div><dt>Balance</dt><dd>{formatMoney(account.balance, account.currency)}</dd></div>
          <div><dt>Equity</dt><dd className={signedClass(Number(account.equity) - Number(account.balance))}>{formatMoney(account.equity, account.currency)}</dd></div>
          <div><dt>Floating P&L</dt><dd className={signedClass(account.floating_pnl)}>{formatMoney(account.floating_pnl, account.currency)}</dd></div>
          <div><dt>Used margin</dt><dd>{formatMoney(account.margin, account.currency)}</dd></div>
          <div><dt>Free margin</dt><dd>{formatMoney(account.free_margin, account.currency)}</dd></div>
          <div><dt>Margin level</dt><dd>{account.margin_level_percent ? formatPercent(account.margin_level_percent) : "—"}</dd></div>
          <div><dt>Drawdown</dt><dd className="negative">{formatMoney(account.drawdown_amount, account.currency)}</dd></div>
        </dl>
      </section>

      <section className="inspector-section">
        <div className="section-title"><ShieldCheck size={15} /><span>Exposure</span></div>
        <div className="position-list">
          {positions.slice(0, 6).map(position => (
            <article key={position.position_id} className="position-card">
              <header>
                <span className={`side-pill ${position.side}`}>{position.side}</span>
                <strong>{position.symbol}</strong>
                <em>{formatNumber(position.volume_lots, 2)} lot</em>
              </header>
              <div>
                <span>Entry {formatNumber(Number(position.average_entry_price_ticks) * tickSize)}</span>
                <strong className={signedClass(position.unrealized_pnl)}>{formatMoney(position.unrealized_pnl, account.currency)}</strong>
              </div>
              <small>
                SL {position.stop_loss_ticks === null ? "—" : formatNumber(position.stop_loss_ticks * tickSize)} · TP {position.take_profit_ticks === null ? "—" : formatNumber(position.take_profit_ticks * tickSize)}
              </small>
            </article>
          ))}
          {positions.length === 0 ? <div className="empty-inline">No open positions</div> : null}
          <div className="exposure-summary">
            <span>{positions.length} positions</span>
            <span>{activeOrderCount} active orders</span>
          </div>
        </div>
      </section>

      <section className="inspector-section">
        <div className="section-title"><Layers3 size={15} /><span>Strategy layers</span></div>
        <div className="layer-list">
          {[...chartLayers].slice(0, 8).map(layer => (
            <div key={layer} className="layer-item">
              <span className="layer-dot" />
              <span>{layer}</span>
              <span className="layer-state">visible</span>
            </div>
          ))}
          {chartLayers.size === 0 ? <div className="empty-inline">No active layers</div> : null}
        </div>
      </section>

      <section className="inspector-section grow">
        <div className="section-title"><ListTree size={15} /><span>Recent events</span></div>
        <div className="event-feed">
          {recent.map(item => (
            <article key={item.sequence} className="event-card">
              <div>
                <span className={`event-kind ${item.kind}`}>{item.kind.replace("_", " ")}</span>
                <time>{formatDateTime(item.time_ns)}</time>
              </div>
              <strong>{eventTitle(item)}</strong>
              <small>Sequence {formatNumber(item.sequence, 0)}</small>
            </article>
          ))}
          {recent.length === 0 ? <div className="empty-state"><RadioTower size={22} /><span>Waiting for replay events</span></div> : null}
        </div>
      </section>
    </aside>
  );
});

function recentChartLayers(timeline: ReplayTimelineItem[], maximum: number): Set<string> {
  const result = new Set<string>();
  for (let index = timeline.length - 1; index >= 0 && result.size < maximum; index -= 1) {
    const item = timeline[index];
    if (!item || item.kind !== "chart_command") continue;
    const payload = item.payload;
    const commandPayload = (payload.drawing ?? payload.series) as Record<string, unknown> | undefined;
    result.add(String(commandPayload?.layer_id ?? "strategy"));
  }
  return result;
}

function eventTitle(item: ReplayTimelineItem): string {
  if (item.kind === "broker_event") return String(item.payload.event_type ?? "Broker event");
  if (item.kind === "chart_command") return String(item.payload.command_type ?? "Chart command");
  if (item.kind === "strategy_action") return String(item.payload.action_type ?? "Strategy action");
  if (item.kind === "strategy_log") return String(item.payload.message ?? "Strategy log");
  return "Account snapshot";
}
