import type { OrderRecord } from "./types";

type UnknownRecord = Record<string, unknown>;

export interface OrderFillEvent {
  order_id: string;
  time_ns: number;
  price_ticks: number;
  volume_lots: string;
}

const orderSides = new Set<OrderRecord["request"]["side"]>(["buy", "sell"]);
const orderTypes = new Set<OrderRecord["request"]["order_type"]>([
  "market",
  "limit",
  "stop"
]);

function record(value: unknown): UnknownRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as UnknownRecord
    : null;
}

function finiteNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || value.trim().length === 0) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function decimalString(value: unknown, fallback: string): string {
  if (typeof value === "string" && value.length > 0) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return fallback;
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function optionalInteger(value: unknown): number | undefined {
  const parsed = finiteNumber(value);
  return parsed !== null && Number.isInteger(parsed) ? parsed : undefined;
}

export function normalizeOrderRecord(value: unknown): OrderRecord | null {
  const source = record(value);
  const requestSource = record(source?.request);
  if (!source || !requestSource) return null;

  const orderId = source.order_id;
  const clientOrderId = requestSource.client_order_id;
  const symbol = requestSource.symbol;
  const side = requestSource.side;
  const orderType = requestSource.order_type;
  const createdTimeNs = finiteNumber(requestSource.created_time_ns);

  if (
    typeof orderId !== "string"
    || typeof clientOrderId !== "string"
    || typeof symbol !== "string"
    || !orderSides.has(side as OrderRecord["request"]["side"])
    || !orderTypes.has(orderType as OrderRecord["request"]["order_type"])
    || createdTimeNs === null
  ) {
    return null;
  }

  const request: OrderRecord["request"] = {
    client_order_id: clientOrderId,
    symbol,
    side: side as OrderRecord["request"]["side"],
    order_type: orderType as OrderRecord["request"]["order_type"],
    volume_lots: decimalString(requestSource.volume_lots, "0"),
    created_time_ns: createdTimeNs,
    reduce_only: requestSource.reduce_only === true
  };

  const priceTicks = optionalInteger(requestSource.price_ticks);
  const stopLossTicks = optionalInteger(requestSource.stop_loss_ticks);
  const takeProfitTicks = optionalInteger(requestSource.take_profit_ticks);
  const positionId = requestSource.position_id;

  if (priceTicks !== undefined) request.price_ticks = priceTicks;
  if (stopLossTicks !== undefined) request.stop_loss_ticks = stopLossTicks;
  if (takeProfitTicks !== undefined) request.take_profit_ticks = takeProfitTicks;
  if (typeof positionId === "string") request.position_id = positionId;

  return {
    order_id: orderId,
    request,
    status: typeof source.status === "string" ? source.status : "unknown",
    filled_volume_lots: decimalString(source.filled_volume_lots, "0"),
    average_fill_price_ticks: nullableString(source.average_fill_price_ticks),
    terminal_time_ns: finiteNumber(source.terminal_time_ns),
    rejection_reason: nullableString(source.rejection_reason)
  };
}

export function normalizeOrderRecords(values: readonly unknown[]): OrderRecord[] {
  const normalized: OrderRecord[] = [];
  for (const value of values) {
    const order = normalizeOrderRecord(value);
    if (order) normalized.push(order);
  }
  return normalized;
}

export function normalizeOrderFillEvent(value: unknown): OrderFillEvent | null {
  const source = record(value);
  if (!source || typeof source.order_id !== "string") return null;

  const timeNs = finiteNumber(source.time_ns);
  const priceTicks = finiteNumber(source.price_ticks);
  if (timeNs === null || priceTicks === null) return null;

  return {
    order_id: source.order_id,
    time_ns: timeNs,
    price_ticks: priceTicks,
    volume_lots: decimalString(source.volume_lots, "0")
  };
}

export function applyOrderFill(order: OrderRecord, fill: OrderFillEvent): OrderRecord {
  return {
    ...order,
    status: "filled",
    filled_volume_lots: fill.volume_lots,
    average_fill_price_ticks: String(fill.price_ticks),
    terminal_time_ns: fill.time_ns,
    rejection_reason: null
  };
}

export function orderCreatedTimeNs(order: OrderRecord): number {
  return finiteNumber(order.request?.created_time_ns) ?? order.terminal_time_ns ?? 0;
}
