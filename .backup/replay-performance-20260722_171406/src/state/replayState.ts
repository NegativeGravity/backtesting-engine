import {
  emptyChartState,
  materializeChartState,
  type MaterializedChartState
} from "../chart/chartState";
import { CHART_BAR_WINDOW, REPLAY_TIMELINE_WINDOW } from "../chart/performanceLimits";
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

const MAX_UI_ORDERS = 5_000;
const MAX_UI_TRADES = 5_000;
const MAX_UI_FILLS = 5_000;

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

  let nextOrders = orders;
  let nextPositions = positions;
  let nextTrades = trades;
  let orderMap: Map<string, OrderRecord> | null = null;
  let positionMap: Map<string, PositionRecord> | null = null;
  let tradeMap: Map<string, TradeRecord> | null = null;

  const mutableOrders = (): Map<string, OrderRecord> => {
    if (!orderMap) {
      orderMap = new Map(normalizeOrderRecords(nextOrders).map(order => [order.order_id, order]));
    }
    return orderMap;
  };
  const mutablePositions = (): Map<string, PositionRecord> => {
    if (!positionMap) {
      positionMap = new Map(nextPositions.map(position => [position.position_id, position]));
    }
    return positionMap;
  };
  const mutableTrades = (): Map<string, TradeRecord> => {
    if (!tradeMap) {
      tradeMap = new Map(nextTrades.map(trade => [trade.trade_id, trade]));
    }
    return tradeMap;
  };

  for (const item of items) {
    if (item.kind !== "broker_event") continue;
    const event = item.payload;
    const eventType = String(event.event_type ?? "");
    const payload = event.payload;

    if (eventType.startsWith("order.")) {
      const ordersById = mutableOrders();
      const order = normalizeOrderRecord(payload);
      if (order) {
        ordersById.set(order.order_id, order);
      } else if (eventType === "order.filled") {
        const fill = normalizeOrderFillEvent(payload);
        const existing = fill ? ordersById.get(fill.order_id) : undefined;
        if (fill && existing) ordersById.set(fill.order_id, applyOrderFill(existing, fill));
      }
    }

    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) continue;
    const payloadRecord = payload as Record<string, unknown>;

    if (eventType === "account.updated") {
      const snapshotOrders = payloadRecord.orders;
      if (Array.isArray(snapshotOrders)) {
        const normalized = normalizeOrderRecords(snapshotOrders as OrderRecord[])
          .sort((left, right) => orderCreatedTimeNs(left) - orderCreatedTimeNs(right))
          .slice(-MAX_UI_ORDERS);
        nextOrders = sameOrderSnapshot(nextOrders, normalized) ? nextOrders : normalized;
        orderMap = null;
      }

      const snapshotPositions = payloadRecord.positions;
      if (Array.isArray(snapshotPositions)) {
        const normalized = (snapshotPositions as PositionRecord[])
          .slice()
          .sort((left, right) => left.opened_time_ns - right.opened_time_ns);
        nextPositions = samePositionSnapshot(nextPositions, normalized) ? nextPositions : normalized;
        positionMap = null;
      }
    }

    if (
      (eventType === "position.opened" || eventType === "position.updated") &&
      typeof payloadRecord.position_id === "string"
    ) {
      mutablePositions().set(
        payloadRecord.position_id,
        payloadRecord as unknown as PositionRecord
      );
    }

    if (
      (eventType === "position.closed" || eventType === "position.liquidated") &&
      typeof payloadRecord.position_id === "string"
    ) {
      mutablePositions().delete(payloadRecord.position_id);
      const trade = payloadRecord.trade as TradeRecord | undefined;
      if (trade) mutableTrades().set(trade.trade_id, trade);
    }
  }

  const finalOrderMap = orderMap as Map<string, OrderRecord> | null;
  const finalPositionMap = positionMap as Map<string, PositionRecord> | null;
  const finalTradeMap = tradeMap as Map<string, TradeRecord> | null;

  if (finalOrderMap) {
    nextOrders = [...finalOrderMap.values()]
      .sort((left, right) => orderCreatedTimeNs(left) - orderCreatedTimeNs(right))
      .slice(-MAX_UI_ORDERS);
  }
  if (finalPositionMap) {
    nextPositions = [...finalPositionMap.values()]
      .sort((left, right) => left.opened_time_ns - right.opened_time_ns);
  }
  if (finalTradeMap) {
    nextTrades = [...finalTradeMap.values()]
      .sort((left, right) => left.exit_time_ns - right.exit_time_ns)
      .slice(-MAX_UI_TRADES);
  }

  return { orders: nextOrders, positions: nextPositions, trades: nextTrades };
}

function sameOrderSnapshot(left: OrderRecord[], right: OrderRecord[]): boolean {
  if (left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    const leftOrder = left[index];
    const rightOrder = right[index];
    if (!leftOrder || !rightOrder) return false;
    if (
      leftOrder.order_id !== rightOrder.order_id ||
      leftOrder.status !== rightOrder.status ||
      leftOrder.filled_volume_lots !== rightOrder.filled_volume_lots ||
      leftOrder.average_fill_price_ticks !== rightOrder.average_fill_price_ticks ||
      leftOrder.terminal_time_ns !== rightOrder.terminal_time_ns ||
      leftOrder.rejection_reason !== rightOrder.rejection_reason ||
      leftOrder.request.volume_lots !== rightOrder.request.volume_lots ||
      leftOrder.request.price_ticks !== rightOrder.request.price_ticks ||
      leftOrder.request.stop_loss_ticks !== rightOrder.request.stop_loss_ticks ||
      leftOrder.request.take_profit_ticks !== rightOrder.request.take_profit_ticks
    ) return false;
  }
  return true;
}

function samePositionSnapshot(left: PositionRecord[], right: PositionRecord[]): boolean {
  if (left.length !== right.length) return false;
  for (let index = 0; index < left.length; index += 1) {
    const leftPosition = left[index];
    const rightPosition = right[index];
    if (!leftPosition || !rightPosition) return false;
    if (
      leftPosition.position_id !== rightPosition.position_id ||
      leftPosition.status !== rightPosition.status ||
      leftPosition.volume_lots !== rightPosition.volume_lots ||
      leftPosition.average_entry_price_ticks !== rightPosition.average_entry_price_ticks ||
      leftPosition.current_price_ticks !== rightPosition.current_price_ticks ||
      leftPosition.stop_loss_ticks !== rightPosition.stop_loss_ticks ||
      leftPosition.take_profit_ticks !== rightPosition.take_profit_ticks ||
      leftPosition.realized_pnl !== rightPosition.realized_pnl ||
      leftPosition.unrealized_pnl !== rightPosition.unrealized_pnl
    ) return false;
  }
  return true;
}

export function mergeVisibleBars(
  existing: ReplayBootstrap["bars"],
  incoming: ReplayBootstrap["bars"]
): ReplayBootstrap["bars"] {
  if (incoming.length === 0) return existing;
  if (existing.length === 0) return incoming.slice(-CHART_BAR_WINDOW);

  const firstIncoming = incoming[0];
  const lastIncoming = incoming.at(-1);
  const firstExisting = existing[0];
  const lastExisting = existing.at(-1);
  if (!firstIncoming || !lastIncoming || !firstExisting || !lastExisting) {
    return incoming.slice(-CHART_BAR_WINDOW);
  }

  if (firstIncoming.sequence > lastExisting.sequence) {
    const overflow = Math.max(0, existing.length + incoming.length - CHART_BAR_WINDOW);
    return [...existing.slice(overflow), ...incoming];
  }

  if (firstIncoming.sequence === lastExisting.sequence) {
    const replacement = firstIncoming;
    const tail = incoming.slice(1);
    const base = [...existing.slice(0, -1), replacement, ...tail];
    return base.slice(-CHART_BAR_WINDOW);
  }

  if (lastIncoming.sequence < firstExisting.sequence || lastIncoming.sequence < lastExisting.sequence) {
    return incoming.slice(-CHART_BAR_WINDOW);
  }

  const overlapIndex = existing.findIndex(bar => bar.sequence === firstIncoming.sequence);
  if (overlapIndex >= 0) {
    return [...existing.slice(0, overlapIndex), ...incoming].slice(-CHART_BAR_WINDOW);
  }

  const merged = new Map<number, ReplayBootstrap["bars"][number]>();
  for (const bar of existing) merged.set(bar.sequence, bar);
  for (const bar of incoming) merged.set(bar.sequence, bar);
  return [...merged.values()]
    .sort((a, b) => a.sequence - b.sequence)
    .slice(-CHART_BAR_WINDOW);
}

function appendTimeline(
  existing: ReplayTimelineItem[],
  incoming: ReplayTimelineItem[]
): ReplayTimelineItem[] {
  if (incoming.length === 0) return existing;
  const overflow = Math.max(0, existing.length + incoming.length - REPLAY_TIMELINE_WINDOW);
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
    const timeline = action.bootstrap.timeline.slice(-REPLAY_TIMELINE_WINDOW);
    const orders = normalizeOrderRecords(action.bootstrap.orders).slice(-MAX_UI_ORDERS);
    const trades = action.bootstrap.trades.slice(-MAX_UI_TRADES);
    const fills = action.bootstrap.fills.slice(-MAX_UI_FILLS);
    return {
      ...state,
      bootstrap: {
        ...action.bootstrap,
        bars: action.bootstrap.bars.slice(-CHART_BAR_WINDOW),
        timeline,
        orders,
        trades,
        fills
      },
      timeline,
      chartState: materializeChartState(action.bootstrap.timeline),
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
