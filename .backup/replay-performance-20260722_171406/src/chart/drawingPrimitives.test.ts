import { describe, expect, it } from "vitest";
import { buildDrawingPrimitives } from "./drawingPrimitives";
import type { DrawingState } from "./chartState";

function state(payload: Record<string, unknown>): DrawingState {
  return { drawingId: "open", revision: 1, payload };
}

describe("buildDrawingPrimitives", () => {
  it("extends an open broker trade to the latest replay candle without rebuilding the drawing", () => {
    const primitives = buildDrawingPrimitives(
      [state({
        kind: "broker_trade",
        status: "open",
        side: "long",
        entry_time_ns: 10,
        exit_time_ns: null,
        entry_price_ticks: 100,
        exit_price_ticks: 101,
        stop_price_ticks: 95,
        target_price_ticks: 110,
        net_pnl: 1,
        exit_kind: "open",
        visible: true
      })],
      {
        timeToX: timeNs => timeNs,
        priceToY: price => price
      },
      1,
      1_000,
      1_000,
      100
    );

    const horizontalLines = primitives.filter(primitive => primitive.kind === "line");
    expect(horizontalLines.some(primitive => primitive.kind === "line" && primitive.x2 === 100)).toBe(true);
  });
});
