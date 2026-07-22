export interface PriceRange {
  from: number;
  to: number;
}

export interface CapturedTimeViewport {
  barsVisible: number;
  rightOffset: number;
}

export interface ChartViewportSettings {
  followLatest: boolean;
  lockTimeScale: boolean;
  barsVisible: number;
  rightOffset: number;
  priceScaleMode: "auto" | "locked";
  priceRange: PriceRange | null;
}

export const DEFAULT_CHART_VIEWPORT: ChartViewportSettings = {
  followLatest: true,
  lockTimeScale: true,
  barsVisible: 160,
  rightOffset: 12,
  priceScaleMode: "auto",
  priceRange: null
};

export function normalizeViewportSettings(
  value: Partial<ChartViewportSettings> | null | undefined
): ChartViewportSettings {
  const barsVisible = clampInteger(value?.barsVisible, 40, 1200, 160);
  const rightOffset = clampInteger(value?.rightOffset, 0, 100, 12);
  const range = normalizePriceRange(value?.priceRange);
  const priceScaleMode = value?.priceScaleMode === "locked" && range ? "locked" : "auto";
  return {
    followLatest: value?.followLatest ?? true,
    lockTimeScale: value?.lockTimeScale ?? true,
    barsVisible,
    rightOffset,
    priceScaleMode,
    priceRange: priceScaleMode === "locked" ? range : null
  };
}

export function latestLogicalRange(
  barCount: number,
  settings: ChartViewportSettings
): PriceRange | null {
  if (barCount <= 0) return null;
  const to = barCount - 1 + settings.rightOffset;
  return { from: to - settings.barsVisible, to };
}

export function viewportStorageKey(symbol: string, timeframe: string): string {
  return `vex.chart.viewport.v2.${symbol}.${timeframe}`;
}

export function loadViewportSettings(symbol: string, timeframe: string): ChartViewportSettings {
  if (typeof window === "undefined") return DEFAULT_CHART_VIEWPORT;
  const raw = window.localStorage.getItem(viewportStorageKey(symbol, timeframe));
  if (!raw) return DEFAULT_CHART_VIEWPORT;
  try {
    return normalizeViewportSettings(JSON.parse(raw) as Partial<ChartViewportSettings>);
  } catch {
    return DEFAULT_CHART_VIEWPORT;
  }
}

export function saveViewportSettings(
  symbol: string,
  timeframe: string,
  settings: ChartViewportSettings
): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(
    viewportStorageKey(symbol, timeframe),
    JSON.stringify(normalizeViewportSettings(settings))
  );
}

function normalizePriceRange(value: PriceRange | null | undefined): PriceRange | null {
  if (!value) return null;
  const from = Number(value.from);
  const to = Number(value.to);
  if (!Number.isFinite(from) || !Number.isFinite(to) || from >= to) return null;
  return { from, to };
}

function clampInteger(
  value: number | undefined,
  minimum: number,
  maximum: number,
  fallback: number
): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.min(maximum, Math.max(minimum, Math.round(Number(value))));
}
