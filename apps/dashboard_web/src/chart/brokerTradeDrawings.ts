import type { DrawingState } from "./chartState";
import type { PositionRecord, TradeRecord } from "../lib/types";

const CLOSED_TRADE_LIMIT = 1_500;

export interface BrokerTradeDrawingInput {
  symbol: string;
  trades: TradeRecord[];
  positions: PositionRecord[];
  latestTimeNs: number | null;
}

export function buildBrokerTradeDrawings({
  symbol,
  trades,
  positions,
  latestTimeNs
}: BrokerTradeDrawingInput): DrawingState[] {
  return [
    ...buildClosedTradeDrawings({ symbol, trades }),
    ...buildOpenPositionDrawings({ symbol, positions, latestTimeNs })
  ];
}

export function buildClosedTradeDrawings({
  symbol,
  trades
}: Pick<BrokerTradeDrawingInput, "symbol" | "trades">): DrawingState[] {
  return trades
    .filter(trade => trade.symbol === symbol)
    .slice(-CLOSED_TRADE_LIMIT)
    .map(toClosedTradeDrawing);
}

export function buildOpenPositionDrawings({
  symbol,
  positions,
  latestTimeNs
}: Pick<BrokerTradeDrawingInput, "symbol" | "positions" | "latestTimeNs">): DrawingState[] {
  return positions
    .filter(position => position.symbol === symbol)
    .map(position => toOpenPositionDrawing(position, latestTimeNs));
}

export function brokerTradeIds(drawings: Iterable<DrawingState>): Set<string> {
  const result = new Set<string>();
  for (const drawing of drawings) {
    const tradeId = String(drawing.payload.trade_id ?? "");
    if (tradeId) result.add(tradeId);
  }
  return result;
}

function toClosedTradeDrawing(trade: TradeRecord): DrawingState {
  const exitKind = normalizeExitKind(trade.exit_reason);
  return {
    drawingId: `broker-trade:${trade.trade_id}`,
    revision: 1,
    payload: {
      kind: "broker_trade",
      drawing_id: `broker-trade:${trade.trade_id}`,
      layer_id: "broker-trades",
      trade_id: trade.trade_id,
      position_id: trade.position_id,
      symbol: trade.symbol,
      side: trade.side,
      status: "closed",
      entry_time_ns: trade.entry_time_ns,
      exit_time_ns: trade.exit_time_ns,
      entry_price_ticks: numeric(trade.entry_price_ticks),
      exit_price_ticks: numeric(trade.exit_price_ticks),
      stop_price_ticks: nullableNumeric(trade.stop_loss_ticks),
      target_price_ticks: nullableNumeric(trade.take_profit_ticks),
      net_pnl: numeric(trade.net_pnl),
      realized_r_multiple: nullableNumeric(trade.realized_r_multiple),
      exit_reason: trade.exit_reason,
      exit_kind: exitKind,
      intrabar_ambiguous: trade.intrabar_ambiguous,
      visible: true
    }
  };
}

function toOpenPositionDrawing(
  position: PositionRecord,
  latestTimeNs: number | null
): DrawingState {
  const entry = numeric(position.average_entry_price_ticks);
  return {
    drawingId: `broker-position:${position.position_id}`,
    revision: Math.max(1, Math.floor((latestTimeNs ?? position.opened_time_ns) / 1_000_000_000)),
    payload: {
      kind: "broker_trade",
      drawing_id: `broker-position:${position.position_id}`,
      layer_id: "broker-trades",
      trade_id: "",
      position_id: position.position_id,
      symbol: position.symbol,
      side: position.side,
      status: "open",
      entry_time_ns: position.opened_time_ns,
      exit_time_ns: Math.max(position.opened_time_ns, latestTimeNs ?? position.opened_time_ns),
      entry_price_ticks: entry,
      exit_price_ticks: nullableNumeric(position.current_price_ticks) ?? entry,
      stop_price_ticks: nullableNumeric(position.stop_loss_ticks),
      target_price_ticks: nullableNumeric(position.take_profit_ticks),
      net_pnl: numeric(position.unrealized_pnl),
      realized_r_multiple: null,
      exit_reason: "open",
      exit_kind: "open",
      intrabar_ambiguous: false,
      visible: true
    }
  };
}

export function normalizeExitKind(reason: string): "take_profit" | "stop_loss" | "liquidation" | "manual" | "open" {
  const value = reason.trim().toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
  if (value.includes("take_profit") || value === "tp" || value.includes("target")) return "take_profit";
  if (value.includes("stop_loss") || value === "sl" || value.includes("stop")) return "stop_loss";
  if (value.includes("liquidat") || value.includes("margin")) return "liquidation";
  if (value === "open") return "open";
  return "manual";
}

function numeric(value: string | number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function nullableNumeric(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
