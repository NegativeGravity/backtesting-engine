import { memo, useMemo } from "react";
import { BarChart3, Braces, ClipboardList, ListOrdered, ScrollText } from "lucide-react";
import { formatDateTime, formatMoney, formatNumber, signedClass } from "../lib/format";
import { normalizeOrderRecords } from "../lib/orderRuntime";
import type {
  AccountSnapshot,
  OrderRecord,
  ReplayMetrics,
  ReplayTimelineItem,
  TradeRecord
} from "../lib/types";
import type { ReplayState } from "../state/replayState";

interface Props {
  activeTab: ReplayState["activeBottomTab"];
  onTabChange: (tab: ReplayState["activeBottomTab"]) => void;
  trades: TradeRecord[];
  orders: OrderRecord[];
  timeline: ReplayTimelineItem[];
  metrics: ReplayMetrics;
  account: AccountSnapshot;
  tickSize: number;
}

const MAX_DOCK_ROWS = 300;

const tabs = [
  { id: "trades" as const, label: "Trades", icon: ClipboardList },
  { id: "orders" as const, label: "Orders", icon: ListOrdered },
  { id: "events" as const, label: "Events", icon: Braces },
  { id: "logs" as const, label: "Logs", icon: ScrollText },
  { id: "metrics" as const, label: "Performance", icon: BarChart3 }
];

export const BottomDock = memo(function BottomDock({
  activeTab,
  onTabChange,
  trades,
  orders,
  timeline,
  metrics,
  account,
  tickSize
}: Props) {
  const events = useMemo(() => timeline.filter(item => item.kind !== "strategy_log").slice(-MAX_DOCK_ROWS), [timeline]);
  const logs = useMemo(() => timeline.filter(item => item.kind === "strategy_log").slice(-MAX_DOCK_ROWS), [timeline]);
  return (
    <section className="bottom-dock">
      <nav className="dock-tabs">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button key={id} className={activeTab === id ? "active" : ""} onClick={() => onTabChange(id)}>
            <Icon size={14} />
            <span>{label}</span>
            {id === "trades" ? <em>{trades.length}</em> : null}
            {id === "orders" ? <em>{orders.length}</em> : null}
          </button>
        ))}
      </nav>
      <div className="dock-content">
        {activeTab === "trades" ? <TradesTable trades={trades} currency={account.currency} tickSize={tickSize} /> : null}
        {activeTab === "orders" ? <OrdersTable orders={orders} tickSize={tickSize} /> : null}
        {activeTab === "events" ? <EventsTable timeline={events} /> : null}
        {activeTab === "logs" ? <LogsTable timeline={logs} /> : null}
        {activeTab === "metrics" ? <PerformancePanel trades={trades} metrics={metrics} currency={account.currency} /> : null}
      </div>
    </section>
  );
});

function TradesTable({ trades, currency, tickSize }: { trades: TradeRecord[]; currency: string; tickSize: number }) {
  if (trades.length === 0) return <EmptyTable text="No completed trades at the current replay position" />;
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th>Trade</th><th>Side</th><th>Entry</th><th>Exit</th><th>Volume</th><th>Net P&L</th><th>R</th><th>Reason</th></tr></thead>
        <tbody>{trades.slice(-MAX_DOCK_ROWS).map(trade => (
          <tr key={trade.trade_id}>
            <td><strong>{trade.trade_id}</strong><small>{formatDateTime(trade.exit_time_ns)}</small></td>
            <td><span className={`side-pill ${trade.side}`}>{trade.side}</span></td>
            <td>{formatNumber(Number(trade.entry_price_ticks) * tickSize)}</td>
            <td>{formatNumber(Number(trade.exit_price_ticks) * tickSize)}</td>
            <td>{formatNumber(trade.volume_lots, 2)}</td>
            <td className={signedClass(trade.net_pnl)}>{formatMoney(trade.net_pnl, currency)}</td>
            <td>{trade.realized_r_multiple ? `${formatNumber(trade.realized_r_multiple)}R` : "—"}</td>
            <td>{trade.exit_reason}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function OrdersTable({ orders, tickSize }: { orders: OrderRecord[]; tickSize: number }) {
  const visibleOrders = useMemo(
    () => normalizeOrderRecords(orders).slice(-MAX_DOCK_ROWS),
    [orders]
  );
  if (visibleOrders.length === 0) return <EmptyTable text="No orders at the current replay position" />;
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th>Order</th><th>Created</th><th>Side</th><th>Type</th><th>Volume</th><th>Price</th><th>Status</th></tr></thead>
        <tbody>{visibleOrders.map(order => (
          <tr key={order.order_id}>
            <td><strong>{order.request.client_order_id}</strong><small>{order.order_id}</small></td>
            <td>{formatDateTime(order.request.created_time_ns)}</td>
            <td><span className={`side-pill ${order.request.side}`}>{order.request.side}</span></td>
            <td>{order.request.order_type}</td>
            <td>{formatNumber(order.request.volume_lots, 2)}</td>
            <td>{order.average_fill_price_ticks ? formatNumber(Number(order.average_fill_price_ticks) * tickSize) : "—"}</td>
            <td><span className={`status-pill ${order.status}`}>{order.status}</span></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function EventsTable({ timeline }: { timeline: ReplayTimelineItem[] }) {
  const events = timeline.slice(-MAX_DOCK_ROWS).reverse();
  if (events.length === 0) return <EmptyTable text="No events at the current replay position" />;
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th>Sequence</th><th>Time</th><th>Kind</th><th>Event</th></tr></thead>
        <tbody>{events.map(item => (
          <tr key={item.sequence}>
            <td>{item.sequence}</td>
            <td>{formatDateTime(item.time_ns)}</td>
            <td><span className={`event-kind ${item.kind}`}>{item.kind.replace("_", " ")}</span></td>
            <td>{eventDescription(item)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function LogsTable({ timeline }: { timeline: ReplayTimelineItem[] }) {
  if (timeline.length === 0) return <EmptyTable text="No strategy logs at the current replay position" />;
  return (
    <div className="log-console">
      {timeline.map(item => (
        <div key={item.sequence} className={`log-line ${String(item.payload.level ?? "info")}`}>
          <time>{formatDateTime(item.time_ns)}</time>
          <span>{String(item.payload.level ?? "info").toUpperCase()}</span>
          <strong>{String(item.payload.message ?? "")}</strong>
          <code>{JSON.stringify(item.payload.fields ?? {})}</code>
        </div>
      ))}
    </div>
  );
}

function PerformancePanel({ trades, metrics, currency }: { trades: TradeRecord[]; metrics: ReplayMetrics; currency: string }) {
  const months = monthlyPerformance(trades);
  return (
    <div className="performance-panel">
      <div className="performance-summary">
        <article><span>Gross P&L</span><strong className={signedClass(metrics.gross_pnl)}>{formatMoney(metrics.gross_pnl, currency)}</strong></article>
        <article><span>Trading costs</span><strong className="negative">{formatMoney(Number(metrics.commission) + Number(metrics.spread_cost) + Number(metrics.slippage_cost), currency)}</strong></article>
        <article><span>Long / Short</span><strong>{metrics.long_trades} / {metrics.short_trades}</strong></article>
        <article><span>Wins / Losses</span><strong>{metrics.winning_trades} / {metrics.losing_trades}</strong></article>
      </div>
      <div className="monthly-grid">
        <div className="month-header year-header">Year</div>
        {monthNames.map(month => <div key={month} className="month-header">{month}</div>)}
        {[...months.entries()].map(([year, values]) => [
          <div key={`${year}-year`} className="year-cell">{year}</div>,
          ...monthNames.map((_, index) => {
            const value = values[index] ?? { pnl: 0, trades: 0 };
            const intensity = Math.min(0.72, Math.abs(value.pnl) / Math.max(1, Math.abs(Number(metrics.net_pnl))) + 0.08);
            return (
              <div
                key={`${year}-${index}`}
                className={`month-cell ${signedClass(value.pnl)}`}
                style={{ "--cell-intensity": intensity } as React.CSSProperties}
              >
                <strong>{formatMoney(value.pnl, currency)}</strong>
                <span>{value.trades} trades</span>
              </div>
            );
          })
        ])}
      </div>
    </div>
  );
}

function EmptyTable({ text }: { text: string }) {
  return <div className="empty-table">{text}</div>;
}

function eventDescription(item: ReplayTimelineItem): string {
  if (item.kind === "broker_event") return String(item.payload.event_type ?? "Broker event");
  if (item.kind === "chart_command") return String(item.payload.command_type ?? "Chart command");
  if (item.kind === "strategy_action") return String(item.payload.action_type ?? "Strategy action");
  return "Account snapshot";
}

const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthlyPerformance(trades: TradeRecord[]): Map<number, Array<{ pnl: number; trades: number }>> {
  const result = new Map<number, Array<{ pnl: number; trades: number }>>();
  for (const trade of trades) {
    const date = new Date(trade.exit_time_ns / 1_000_000);
    const year = date.getUTCFullYear();
    const month = date.getUTCMonth();
    const values = result.get(year) ?? Array.from({ length: 12 }, () => ({ pnl: 0, trades: 0 }));
    const current = values[month];
    if (current) {
      current.pnl += Number(trade.net_pnl);
      current.trades += 1;
    }
    result.set(year, values);
  }
  if (result.size === 0) result.set(new Date().getUTCFullYear(), Array.from({ length: 12 }, () => ({ pnl: 0, trades: 0 })));
  return result;
}
