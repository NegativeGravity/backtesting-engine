import type { ReplayBar } from "../lib/types";
import type { ChartAdapter, ChartCoordinates, VisibleTimeRangeNs } from "./ChartAdapter";
import type { MaterializedChartState } from "./chartState";
import type {
  CapturedTimeViewport,
  ChartViewportSettings,
  PriceRange
} from "./chartViewport";

export class AdvancedChartsAdapter implements ChartAdapter {
  mount(): void {
    throw new Error("TradingView Advanced Charts assets are not installed");
  }

  destroy(): void {}

  setBars(_bars: ReplayBar[]): void {}

  updateBars(_bars: ReplayBar[]): void {}

  setStrategyState(_state: MaterializedChartState, _tickSize: number): void {}

  applyViewport(_settings: ChartViewportSettings): void {}

  capturePriceRange(): PriceRange | null {
    return null;
  }

  captureTimeViewport(): CapturedTimeViewport | null {
    return null;
  }

  visibleTimeRangeNs(): VisibleTimeRangeNs | null {
    return null;
  }

  fitContent(): void {}

  coordinates(): ChartCoordinates {
    return {
      timeToX: () => null,
      priceToY: () => null
    };
  }

  subscribeRender(): () => void {
    return () => undefined;
  }
}
