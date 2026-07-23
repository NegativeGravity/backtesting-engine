import {
  emptyChartState,
  materializeChartState,
  type MaterializedChartState
} from "../chart/chartState";
import {
  applyOrderFill,
  normalizeOrderFillEvent,
  normalizeOrderRecord,
  normalizeOrderRecords,
  orderCreatedTimeNs
} from "../lib/orderRuntime";
import type {
  AccountSnapshot,
  OrderRecord,
  PositionRecord,
  ReplayBootstrap,
  ReplayCatalog,
  ReplayFrame,
  ReplayTimelineItem,
  TradeRecord
} from "../lib/types";

export type ConnectionStatus = "idle" | "connecting" | "connected" | "disconnected" | "error";

export interface ReplayState {
  catalog: ReplayCatalog | null;
  selectedRunId: string | null;
  bootstrap: ReplayBootstrap | null;
  timeline: ReplayTimelineItem[];
  chartState: MaterializedChartState;
  account: AccountSnapshot | null;
  orders: OrderRecord[];
  positions: PositionRecord[];
  trades: TradeRecord[];
  connection: ConnectionStatus;
  error: string | null;
  activeBottomTab: "trades" | "orders" | "events" | "logs" | "metrics";
  inspectorOpen: boolean;
}

export type ReplayAction =
  | { type: "catalog_loaded"; catalog: ReplayCatalog }
  | { type: "run_selected"; runId: string }
  | { type: "bootstrap_received"; bootstrap: ReplayBootstrap }
  | { type: "frame_received"; frame: ReplayFrame }
  | { type: "connection_changed"; connection: ConnectionStatus }
  | { type: "error"; error: string | null }
  | { type: "bottom_tab_changed"; tab: ReplayState["activeBottomTab"] }
  | { type: "inspector_toggled" };

const MAX_VISIBLE_TIMELINE_ITEMS = 2_000;
const MAX_VISIBLE_BARS = 2_400;
const MAX_UI_ORDERS = 2_000;
const MAX_UI_TRADES = 2_000;
const MAX_UI_FILLS = 2_000;

export const initialReplayState: ReplayState = {
  catalog: null,
  selectedRunId: null,
  bootstrap: null,
  timeline: [],
  chartState: emptyChartState(),
  account: null,
  orders: [],
  positions: [],
  trades: [],
  connection: "idle",
  error: null,
  activeBottomTab: "trades",
  inspectorOpen: true
};

function updateBrokerState(
  orders: OrderRecord[],
  positions: PositionRecord[],
  trades: TradeRecord[],
  items: ReplayTimelineItem[]
): { orders: OrderRecord[]; positions: PositionRecord[]; trades: TradeRecord[] } {
  if (!items.some(item => item.kind === "broker_event")) {
    return { orders, positions, trades };
  }
  const orderMap = new Map(
    normalizeOrderRecords(orders).map(item => [item.order_id, item])
  );
  const positionMap = new Map(positions.map(item => [item.position_id, item]));
  const tradeMap = new Map(trades.map(item => [item.trade_id, item]));
  for (const item of items) {
    if (item.kind !== "broker_event") continue;
    const event = item.payload;
    const eventType = String(event.event_type ?? "");
    const payload = event.payload;

    if (eventType.startsWith("order.")) {
      const order = normalizeOrderRecord(payload);
      if (order) {
        orderMap.set(order.order_id, order);
      } else if (eventType === "order.filled") {
        const fill = normalizeOrderFillEvent(payload);
        const existing = fill ? orderMap.get(fill.order_id) : undefined;
        if (fill && existing) orderMap.set(fill.order_id, applyOrderFill(existing, fill));
      }
    }

    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) continue;
    const payloadRecord = payload as Record<string, unknown>;
    if (eventType === "account.updated") {
      const snapshotOrders = payloadRecord.orders;
      if (Array.isArray(snapshotOrders)) {
        orderMap.clear();
        for (const value of normalizeOrderRecords(snapshotOrders as OrderRecord[])) {
          orderMap.set(value.order_id, value);
        }
      }
      const snapshotPositions = payloadRecord.positions;
      if (Array.isArray(snapshotPositions)) {
        positionMap.clear();
        for (const value of snapshotPositions as PositionRecord[]) {
          positionMap.set(value.position_id, value);
        }
      }
    }
    if ((eventType === "position.opened" || eventType === "position.updated") && typeof payloadRecord.position_id === "string") {
      positionMap.set(payloadRecord.position_id, payloadRecord as unknown as PositionRecord);
    }
    if ((eventType === "position.closed" || eventType === "position.liquidated") && typeof payloadRecord.position_id === "string") {
      positionMap.delete(payloadRecord.position_id);
      const trade = payloadRecord.trade as TradeRecord | undefined;
      if (trade) tradeMap.set(trade.trade_id, trade);
    }
  }
  return {
    orders: [...orderMap.values()]
      .sort((a, b) => orderCreatedTimeNs(a) - orderCreatedTimeNs(b))
      .slice(-MAX_UI_ORDERS),
    positions: [...positionMap.values()].sort((a, b) => a.opened_time_ns - b.opened_time_ns),
    trades: [...tradeMap.values()]
      .sort((a, b) => a.exit_time_ns - b.exit_time_ns)
      .slice(-MAX_UI_TRADES)
  };
}

export function mergeVisibleBars(
  existing: ReplayBootstrap["bars"],
  incoming: ReplayBootstrap["bars"]
): ReplayBootstrap["bars"] {
  if (incoming.length === 0) return existing;
  if (existing.length === 0) return incoming.slice(-MAX_VISIBLE_BARS);

  const firstIncoming = incoming[0];
  const lastIncoming = incoming.at(-1);
  const firstExisting = existing[0];
  const lastExisting = existing.at(-1);
  if (!firstIncoming || !lastIncoming || !firstExisting || !lastExisting) {
    return incoming.slice(-MAX_VISIBLE_BARS);
  }

  if (firstIncoming.sequence > lastExisting.sequence) {
    const overflow = Math.max(0, existing.length + incoming.length - MAX_VISIBLE_BARS);
    return [...existing.slice(overflow), ...incoming];
  }

  if (firstIncoming.sequence === lastExisting.sequence) {
    const replacement = firstIncoming;
    const tail = incoming.slice(1);
    const base = [...existing.slice(0, -1), replacement, ...tail];
    return base.slice(-MAX_VISIBLE_BARS);
  }

  if (lastIncoming.sequence < firstExisting.sequence || lastIncoming.sequence < lastExisting.sequence) {
    return incoming.slice(-MAX_VISIBLE_BARS);
  }

  const overlapIndex = existing.findIndex(bar => bar.sequence === firstIncoming.sequence);
  if (overlapIndex >= 0) {
    return [...existing.slice(0, overlapIndex), ...incoming].slice(-MAX_VISIBLE_BARS);
  }

  const merged = new Map<number, ReplayBootstrap["bars"][number]>();
  for (const bar of existing) merged.set(bar.sequence, bar);
  for (const bar of incoming) merged.set(bar.sequence, bar);
  return [...merged.values()]
    .sort((a, b) => a.sequence - b.sequence)
    .slice(-MAX_VISIBLE_BARS);
}

function appendTimeline(
  existing: ReplayTimelineItem[],
  incoming: ReplayTimelineItem[]
): ReplayTimelineItem[] {
  if (incoming.length === 0) return existing;
  const overflow = Math.max(0, existing.length + incoming.length - MAX_VISIBLE_TIMELINE_ITEMS);
  return [...existing.slice(overflow), ...incoming];
}

export function replayReducer(state: ReplayState, action: ReplayAction): ReplayState {
  if (action.type === "catalog_loaded") {
    return {
      ...state,
      catalog: action.catalog,
      selectedRunId: action.catalog.runs.some(run => run.run_id === state.selectedRunId)
        ? state.selectedRunId
        : action.catalog.runs[0]?.run_id ?? null
    };
  }
  if (action.type === "run_selected") {
    return {
      ...state,
      selectedRunId: action.runId,
      bootstrap: null,
      timeline: [],
      chartState: emptyChartState(),
      account: null,
      orders: [],
      positions: [],
      trades: [],
      error: null
    };
  }
  if (action.type === "bootstrap_received") {
    const timeline = action.bootstrap.timeline.slice(-MAX_VISIBLE_TIMELINE_ITEMS);
    const orders = normalizeOrderRecords(action.bootstrap.orders).slice(-MAX_UI_ORDERS);
    const trades = action.bootstrap.trades.slice(-MAX_UI_TRADES);
    const fills = action.bootstrap.fills.slice(-MAX_UI_FILLS);
    return {
      ...state,
      bootstrap: {
        ...action.bootstrap,
        bars: action.bootstrap.bars.slice(-MAX_VISIBLE_BARS),
        timeline,
        orders,
        trades,
        fills
      },
      timeline,
      chartState: materializeChartState(timeline),
      account: action.bootstrap.account,
      orders,
      positions: action.bootstrap.positions,
      trades,
      error: null
    };
  }
  if (action.type === "frame_received") {
    if (!state.bootstrap) return state;
    const timeline = appendTimeline(state.timeline, action.frame.timeline);
    const broker = updateBrokerState(
      state.orders,
      state.positions,
      state.trades,
      action.frame.timeline
    );
    const account = action.frame.account ?? state.account;
    return {
      ...state,
      bootstrap: {
        ...state.bootstrap,
        cursor_sequence: action.frame.cursor_sequence,
        cursor_time_ns: action.frame.cursor_time_ns,
        progress: action.frame.progress,
        account: account ?? state.bootstrap.account
      },
      timeline,
      account,
      orders: broker.orders,
      positions: broker.positions,
      trades: broker.trades
    };
  }
  if (action.type === "connection_changed") return { ...state, connection: action.connection };
  if (action.type === "error") return { ...state, error: action.error };
  if (action.type === "bottom_tab_changed") return { ...state, activeBottomTab: action.tab };
  if (action.type === "inspector_toggled") return { ...state, inspectorOpen: !state.inspectorOpen };
  return state;
}
