import type { ReplayBar } from "../lib/types";
import type { MaterializedChartState } from "./chartState";
import type {
  CapturedTimeViewport,
  ChartViewportSettings,
  PriceRange
} from "./chartViewport";

export type ChartRenderReason = "data" | "strategy" | "viewport" | "resize";

export interface VisibleTimeRangeNs {
  from: number;
  to: number;
}

export interface ChartCoordinates {
  timeToX(timeNs: number): number | null;
  priceToY(price: number): number | null;
}

export interface ChartAdapter {
  mount(container: HTMLElement): void;
  destroy(): void;
  setBars(bars: ReplayBar[]): void;
  updateBars(bars: ReplayBar[]): void;
  setStrategyState(state: MaterializedChartState, tickSize: number): void;
  applyViewport(settings: ChartViewportSettings): void;
  capturePriceRange(): PriceRange | null;
  captureTimeViewport(): CapturedTimeViewport | null;
  visibleTimeRangeNs(): VisibleTimeRangeNs | null;
  fitContent(): void;
  coordinates(): ChartCoordinates;
  subscribeRender(handler: (reason: ChartRenderReason) => void): () => void;
}
