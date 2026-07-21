import { describe, expect, it } from "vitest";
import type { ReplayBar } from "../lib/types";
import { ReplayBarBuffer } from "./ReplayBarBuffer";

function bar(sequence: number): ReplayBar {
  return {
    symbol: "XAUUSD",
    timeframe: "M1",
    sequence,
    open_time_ns: sequence * 60_000_000_000,
    close_time_ns: (sequence + 1) * 60_000_000_000,
    open: "2500",
    high: "2501",
    low: "2499",
    close: "2500.5",
    tick_volume: 1,
    real_volume: "0",
    source_spread_points: 7,
    is_complete: true
  };
}

describe("ReplayBarBuffer", () => {
  it("maintains a bounded ring without shifting the backing array", () => {
    const buffer = new ReplayBarBuffer(3, [bar(1), bar(2), bar(3)]);
    const result = buffer.append([bar(4)]);
    expect(result.windowShifted).toBe(true);
    expect(buffer.toArray().map(item => item.sequence)).toEqual([2, 3, 4]);
  });

  it("replaces the current candle without increasing size", () => {
    const buffer = new ReplayBarBuffer(3, [bar(1), bar(2)]);
    const replacement = { ...bar(2), close: "2500.9" };
    const result = buffer.append([replacement]);
    expect(result.replacedLast?.close).toBe("2500.9");
    expect(buffer.size).toBe(2);
    expect(buffer.last?.close).toBe("2500.9");
  });

  it("rebuilds safely when an out-of-order snapshot arrives", () => {
    const buffer = new ReplayBarBuffer(4, [bar(5), bar(6)]);
    const result = buffer.append([bar(3), bar(4), bar(5)]);
    expect(result.rebuildRequired).toBe(true);
    expect(buffer.toArray().map(item => item.sequence)).toEqual([3, 4, 5, 6]);
  });
});
