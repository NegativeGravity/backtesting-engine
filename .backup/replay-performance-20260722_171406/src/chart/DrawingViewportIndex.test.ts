import { describe, expect, it } from "vitest";
import { DrawingViewportIndex, drawingTimeBounds } from "./DrawingViewportIndex";
import type { DrawingState } from "./chartState";

const HOUR_NS = 60 * 60 * 1_000_000_000;

function drawing(drawingId: string, payload: Record<string, unknown>): DrawingState {
  return { drawingId, revision: 1, payload: { drawing_id: drawingId, visible: true, ...payload } };
}

describe("DrawingViewportIndex", () => {
  it("returns only drawings overlapping the visible time buckets plus global levels", () => {
    const index = new DrawingViewportIndex();
    index.replace([
      drawing("day-1", {
        kind: "rectangle",
        start: { time_ns: HOUR_NS, price_ticks: 1 },
        end: { time_ns: 2 * HOUR_NS, price_ticks: 2 }
      }),
      drawing("day-2", {
        kind: "rectangle",
        start: { time_ns: 30 * HOUR_NS, price_ticks: 1 },
        end: { time_ns: 31 * HOUR_NS, price_ticks: 2 }
      }),
      drawing("level", { kind: "horizontal_line", price_ticks: 1 })
    ]);

    const result = index.query({ from: 0, to: 4 * HOUR_NS });
    expect(result.drawings.map(item => item.drawingId)).toEqual(["day-1", "level"]);
    expect(result.totalCount).toBe(3);
  });

  it("keeps open broker trades dynamic and globally queryable", () => {
    const index = new DrawingViewportIndex();
    index.replace([
      drawing("open", {
        kind: "broker_trade",
        status: "open",
        entry_time_ns: HOUR_NS,
        exit_time_ns: null
      })
    ]);

    expect(index.query({ from: 100 * HOUR_NS, to: 101 * HOUR_NS }).drawings).toHaveLength(1);
  });

  it("extracts time bounds from YJ-style trend lines", () => {
    expect(drawingTimeBounds(drawing("line", {
      kind: "trend_line",
      start: { time_ns: 10, price_ticks: 1 },
      end: { time_ns: 20, price_ticks: 1 }
    }))).toEqual({ from: 10, to: 20 });
  });
});

it("caps global drawings before building the visible selection", () => {
  const index = new DrawingViewportIndex();
  index.replace(Array.from({ length: 2_000 }, (_, value) => ({
    drawingId: `level-${value}`,
    revision: 1,
    payload: { kind: "horizontal_line", price_ticks: value }
  })));

  const result = index.query({ from: 0, to: 1 }, 100);

  expect(result.drawings).toHaveLength(100);
  expect(result.drawings[0]?.drawingId).toBe("level-1900");
});

it("keeps open risk-reward drawings in the dynamic set", () => {
  const index = new DrawingViewportIndex();
  index.replace([{
    drawingId: "open-risk",
    revision: 1,
    payload: {
      kind: "risk_reward",
      status: "open",
      entry_time_ns: 100,
      exit_time_ns: null
    }
  }]);

  expect(index.query({ from: 10_000, to: 20_000 }).drawings[0]?.drawingId).toBe("open-risk");
});
