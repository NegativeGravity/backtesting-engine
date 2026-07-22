import { describe, expect, it } from "vitest";
import {
  DEFAULT_CHART_VIEWPORT,
  latestLogicalRange,
  normalizeViewportSettings
} from "./chartViewport";

describe("chart viewport", () => {
  it("keeps a fixed logical width behind the newest bar", () => {
    const range = latestLogicalRange(500, DEFAULT_CHART_VIEWPORT);
    expect(range).toEqual({ from: 351, to: 511 });
  });

  it("rejects an invalid locked price range", () => {
    const settings = normalizeViewportSettings({
      priceScaleMode: "locked",
      priceRange: { from: 10, to: 5 },
      barsVisible: 5,
      rightOffset: 200
    });
    expect(settings.priceScaleMode).toBe("auto");
    expect(settings.priceRange).toBeNull();
    expect(settings.barsVisible).toBe(40);
    expect(settings.rightOffset).toBe(100);
  });
});
