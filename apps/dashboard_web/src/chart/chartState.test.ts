import { describe, expect, it } from "vitest";
import { materializeChartState } from "./chartState";

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
