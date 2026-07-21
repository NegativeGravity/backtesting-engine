import { describe, expect, it } from "vitest";
import { frameIntervalMs, initialFrameSchedulerStats } from "./frameScheduler";

describe("frame scheduler", () => {
  it("uses a low-latency cadence for normal smooth replay", () => {
    expect(frameIntervalMs("smooth", 5, false)).toBe(16);
    expect(frameIntervalMs("smooth", 100, false)).toBe(33);
  });

  it("reduces rendering pressure for hidden tabs and throughput mode", () => {
    expect(frameIntervalMs("smooth", 1, true)).toBe(250);
    expect(frameIntervalMs("throughput", 250, false)).toBe(120);
  });

  it("creates isolated zeroed statistics", () => {
    const left = initialFrameSchedulerStats();
    const right = initialFrameSchedulerStats();
    left.receivedFrames = 10;
    expect(right.receivedFrames).toBe(0);
  });
});
