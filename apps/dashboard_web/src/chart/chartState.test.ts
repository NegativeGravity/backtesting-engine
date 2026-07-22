import { describe, expect, it } from "vitest";
import { emptyChartState, materializeChartState, pruneChartStateToWindow } from "./chartState";

describe("materializeChartState", () => {
  it("creates series and points in timeline order", () => {
    const state = materializeChartState([
      {
        sequence: 1,
        time_ns: 1,
        kind: "chart_command",
        payload: {
          command_type: "declare_series",
          series: {
            series_id: "close",
            title: "Close",
            kind: "line",
            color: "#ffffff",
            line_width: 2,
            visible: true
          }
        }
      },
      {
        sequence: 2,
        time_ns: 2,
        kind: "chart_command",
        payload: {
          command_type: "append_series_point",
          series_id: "close",
          point: { point_type: "scalar", time_ns: 2, value: "123" }
        }
      }
    ]);
    expect(state.series.get("close")?.title).toBe("Close");
    expect(state.points.get("close")?.[0]?.value).toBe(123);
  });

  it("keeps the newest drawing revision", () => {
    const state = materializeChartState([
      {
        sequence: 1,
        time_ns: 1,
        kind: "chart_command",
        payload: { command_type: "upsert_drawing", drawing: { drawing_id: "a", revision: 2, kind: "marker" } }
      },
      {
        sequence: 2,
        time_ns: 2,
        kind: "chart_command",
        payload: { command_type: "upsert_drawing", drawing: { drawing_id: "a", revision: 1, kind: "marker" } }
      }
    ]);
    expect(state.drawings.get("a")?.revision).toBe(2);
  });
});

it("does not mutate the previous point arrays after cloning", async () => {
  const { applyChartCommand, cloneChartState, emptyChartState } = await import("./chartState");
  const original = emptyChartState();
  original.points.set("close", [{ timeNs: 1, value: 1 }]);
  const cloned = cloneChartState(original);
  applyChartCommand(cloned, {
    command_type: "append_series_point",
    series_id: "close",
    point: { point_type: "scalar", time_ns: 2, value: 2 }
  });
  expect(original.points.get("close")).toHaveLength(1);
  expect(cloned.points.get("close")).toHaveLength(2);
});

it("batches indicator appends without mutating previous point arrays", async () => {
  const { applyChartCommands, emptyChartState } = await import("./chartState");
  const original = emptyChartState();
  original.points.set("sma", [{ timeNs: 1, value: 1 }]);
  const next = applyChartCommands(original, [
    {
      sequence: 1,
      time_ns: 2,
      kind: "chart_command",
      payload: {
        command_type: "append_series_point",
        series_id: "sma",
        point: { point_type: "scalar", time_ns: 2, value: 2 }
      }
    },
    {
      sequence: 2,
      time_ns: 3,
      kind: "chart_command",
      payload: {
        command_type: "append_series_point",
        series_id: "sma",
        point: { point_type: "scalar", time_ns: 3, value: 3 }
      }
    }
  ]);
  expect(original.points.get("sma")).toEqual([{ timeNs: 1, value: 1 }]);
  expect(next.points.get("sma")).toEqual([
    { timeNs: 1, value: 1 },
    { timeNs: 2, value: 2 },
    { timeNs: 3, value: 3 }
  ]);
});

it("does not mark drawing-only frames as strategy-series updates", async () => {
  const { applyChartCommandsMutable, emptyChartState } = await import("./chartState");
  const state = emptyChartState();
  const summary = applyChartCommandsMutable(state, [
    {
      sequence: 1,
      time_ns: 1,
      kind: "chart_command",
      payload: {
        command_type: "upsert_drawing",
        drawing: {
          drawing_id: "level",
          revision: 1,
          kind: "horizontal_line",
          price_ticks: 250000
        }
      }
    }
  ]);
  expect(summary.drawingsChanged).toBe(true);
  expect(summary.seriesChanged).toBe(false);
  expect(summary.seriesPoints).toBe(0);
});

it("compacts indicator points in chunks instead of replacing the whole series every point", async () => {
  const { applyChartCommand, emptyChartState } = await import("./chartState");
  const { SERIES_POINT_HIGH_WATER, SERIES_POINT_TARGET } = await import("./performanceLimits");
  const state = emptyChartState();
  for (let timeNs = 1; timeNs <= SERIES_POINT_HIGH_WATER + 1; timeNs += 1) {
    applyChartCommand(state, {
      command_type: "append_series_point",
      series_id: "close",
      point: { point_type: "scalar", time_ns: timeNs, value: timeNs }
    });
  }
  expect(state.points.get("close")).toHaveLength(SERIES_POINT_TARGET);
  expect(state.points.get("close")?.[0]?.timeNs).toBe(
    SERIES_POINT_HIGH_WATER - SERIES_POINT_TARGET + 2
  );

  applyChartCommand(state, {
    command_type: "append_series_point",
    series_id: "close",
    point: {
      point_type: "scalar",
      time_ns: SERIES_POINT_HIGH_WATER + 2,
      value: SERIES_POINT_HIGH_WATER + 2
    }
  });
  expect(state.points.get("close")).toHaveLength(SERIES_POINT_TARGET + 1);
});

it("prunes indicator points and drawings outside the active chart window", async () => {
  const {
    emptyChartState,
    pruneChartStateToWindow
  } = await import("./chartState");
  const state = emptyChartState();
  state.points.set("close", [
    { timeNs: 10, value: 1 },
    { timeNs: 20, value: 2 },
    { timeNs: 30, value: 3 },
    { timeNs: 40, value: 4 }
  ]);
  state.drawings.set("old", {
    drawingId: "old",
    revision: 1,
    payload: {
      kind: "rectangle",
      start: { time_ns: 1, price_ticks: 1 },
      end: { time_ns: 5, price_ticks: 2 }
    }
  });
  state.drawings.set("visible", {
    drawingId: "visible",
    revision: 1,
    payload: {
      kind: "rectangle",
      start: { time_ns: 25, price_ticks: 1 },
      end: { time_ns: 35, price_ticks: 2 }
    }
  });
  state.drawings.set("open", {
    drawingId: "open",
    revision: 1,
    payload: {
      kind: "risk_reward",
      entry_time_ns: 1,
      exit_time_ns: null
    }
  });

  const summary = pruneChartStateToWindow(state, 25, 40);

  expect(summary.drawingsRemoved).toBe(1);
  expect(state.drawings.has("old")).toBe(false);
  expect(state.drawings.has("visible")).toBe(true);
  expect(state.drawings.has("open")).toBe(true);
  expect(state.points.get("close")).toEqual([
    { timeNs: 20, value: 2 },
    { timeNs: 30, value: 3 },
    { timeNs: 40, value: 4 }
  ]);
});

it("active replay pruning can preserve historical audit drawings", () => {
  const state = emptyChartState();
  state.drawings.set("yj.box.2025-01-03", {
    drawingId: "yj.box.2025-01-03",
    revision: 1,
    payload: {
      kind: "rectangle",
      start: { time_ns: 1, price_ticks: 1 },
      end: { time_ns: 2, price_ticks: 2 }
    }
  });

  const summary = pruneChartStateToWindow(state, 100, 200, 0, false);

  expect(summary.drawingsRemoved).toBe(0);
  expect(state.drawings.has("yj.box.2025-01-03")).toBe(true);
});
