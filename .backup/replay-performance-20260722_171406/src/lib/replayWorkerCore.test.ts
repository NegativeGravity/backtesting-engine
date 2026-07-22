import { describe, expect, it } from "vitest";
import type { ReplayBar, ReplayFrame, ReplayTimelineItem } from "./types";
import { mergeAdvanceFramesFast } from "./replayWorkerCore";

function bar(sequence: number): ReplayBar {
  return {
    symbol: "XAUUSD",
    timeframe: "M1",
    sequence,
    open_time_ns: sequence,
    close_time_ns: sequence + 1,
    open: "1",
    high: "2",
    low: "0",
    close: "1",
    tick_volume: 1,
    real_volume: "0",
    source_spread_points: 0,
    is_complete: true
  };
}

function item(sequence: number): ReplayTimelineItem {
  return {
    sequence,
    time_ns: sequence,
    kind: "strategy_log",
    payload: { sequence }
  };
}

function frame(sequence: number, bars: ReplayBar[], timeline: ReplayTimelineItem[]): ReplayFrame {
  return {
    frame_type: "advance",
    cursor_sequence: sequence,
    cursor_time_ns: sequence,
    progress: "0.5",
    playing: true,
    speed: "100",
    bars,
    timeline,
    account: null
  };
}

describe("mergeAdvanceFramesFast", () => {
  it("merges ordered replay frames and prefers the newest duplicate", () => {
    const replacement = { ...bar(2), close: "1.5" };
    const merged = mergeAdvanceFramesFast(
      frame(2, [bar(1), bar(2)], [item(1), item(2)]),
      frame(3, [replacement, bar(3)], [item(2), item(3)])
    );
    expect(merged.bars.map(value => value.sequence)).toEqual([1, 2, 3]);
    expect(merged.bars[1]?.close).toBe("1.5");
    expect(merged.timeline.map(value => value.sequence)).toEqual([1, 2, 3]);
    expect(merged.cursor_sequence).toBe(3);
  });

  it("keeps only the configured tail under backpressure", () => {
    const merged = mergeAdvanceFramesFast(
      frame(3, [bar(1), bar(2), bar(3)], []),
      frame(5, [bar(4), bar(5)], []),
      { maxBars: 3, maxTimelineItems: 3 }
    );
    expect(merged.bars.map(value => value.sequence)).toEqual([3, 4, 5]);
  });
});
