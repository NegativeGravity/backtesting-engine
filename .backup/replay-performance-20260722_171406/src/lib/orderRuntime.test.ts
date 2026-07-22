import { describe, expect, it } from "vitest";
import {
  applyOrderFill,
  normalizeOrderFillEvent,
  normalizeOrderRecord,
  normalizeOrderRecords
} from "./orderRuntime";

const order = {
  order_id: "ord-1",
  request: {
    client_order_id: "client-1",
    symbol: "XAUUSD",
    side: "buy",
    order_type: "market",
    volume_lots: "0.10",
    created_time_ns: 100,
    reduce_only: false
  },
  status: "active",
  filled_volume_lots: "0",
  average_fill_price_ticks: null,
  terminal_time_ns: null,
  rejection_reason: null
};

describe("order runtime normalization", () => {
  it("accepts an order record and ignores event metadata", () => {
    const normalized = normalizeOrderRecord({ ...order, reason: "cancelled by user" });
    expect(normalized?.order_id).toBe("ord-1");
    expect(normalized?.request.created_time_ns).toBe(100);
  });

  it("rejects fill payloads as order records", () => {
    expect(normalizeOrderRecord({ order_id: "ord-1", time_ns: 200 })).toBeNull();
  });

  it("updates an existing order from an order-filled event", () => {
    const normalized = normalizeOrderRecord(order);
    const fill = normalizeOrderFillEvent({
      order_id: "ord-1",
      time_ns: 200,
      price_ticks: 250123,
      volume_lots: "0.10"
    });
    expect(normalized).not.toBeNull();
    expect(fill).not.toBeNull();
    const filled = applyOrderFill(normalized!, fill!);
    expect(filled.request.client_order_id).toBe("client-1");
    expect(filled.status).toBe("filled");
    expect(filled.average_fill_price_ticks).toBe("250123");
    expect(filled.terminal_time_ns).toBe(200);
  });

  it("drops malformed records instead of exposing them to render code", () => {
    expect(normalizeOrderRecords([order, { order_id: "fill-only" }])).toHaveLength(1);
  });
});
