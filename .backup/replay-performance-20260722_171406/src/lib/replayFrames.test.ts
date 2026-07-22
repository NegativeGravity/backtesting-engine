import { describe, expect, it } from "vitest";
import type { ReplayFrame } from "./types";
import { mergeAdvanceFrames } from "./replayFrames";

function frame(cursor: number): ReplayFrame {
  return {
    frame_type: "advance",
    cursor_sequence: cursor,
    cursor_time_ns: cursor,
    progress: String(cursor / 10),
    playing: true,
    speed: "100",
    bars: [],
    timeline: [],
    account: null
  };
}

describe("mergeAdvanceFrames", () => {
  it("keeps the newest cursor and combines incremental payloads", () => {
    const left = frame(1);
    left.timeline = [{ sequence: 1, time_ns: 1, kind: "strategy_log", payload: {} }];
    const right = frame(2);
    right.timeline = [{ sequence: 2, time_ns: 2, kind: "strategy_log", payload: {} }];
    const merged = mergeAdvanceFrames(left, right);
    expect(merged.cursor_sequence).toBe(2);
    expect(merged.timeline.map(item => item.sequence)).toEqual([1, 2]);
  });
});
