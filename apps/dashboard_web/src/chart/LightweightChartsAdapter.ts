import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  LineSeries,
  TickMarkType,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
  type UTCTimestamp
} from "lightweight-charts";
import type { ReplayBar } from "../lib/types";
import { timeNsToSeconds } from "../lib/format";
import type { ChartAdapter, ChartCoordinates } from "./ChartAdapter";
import type { MaterializedChartState } from "./chartState";
import {
  latestLogicalRange,
  type CapturedTimeViewport,
  type ChartViewportSettings,
  type PriceRange
} from "./chartViewport";

interface LineSeriesState {
  count: number;
  firstTimeNs: number | null;
  lastTimeNs: number | null;
  signature: string;
}

export class LightweightChartsAdapter implements ChartAdapter {
  private chart: IChartApi | null = null;
  private candles: ISeriesApi<"Candlestick"> | null = null;
  private readonly lineSeries = new Map<string, ISeriesApi<"Line">>();
  private readonly lineStates = new Map<string, LineSeriesState>();
  private resizeObserver: ResizeObserver | null = null;
  private readonly renderHandlers = new Set<() => void>();
  private renderFrame: number | null = null;
  private barCount = 0;
  private lastBarTime: UTCTimestamp | null = null;
  private priceViewportSignature = "";
  private timeViewportSignature = "";

  mount(container: HTMLElement): void {
    this.destroy();
    this.chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#080c12" },
        textColor: "#8390a5",
        attributionLogo: true,
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        panes: {
          separatorColor: "#1c2430",
          separatorHoverColor: "#2b3748",
          enableResize: true
        }
      },
      localization: {
        locale: "en-GB",
        timeFormatter: (time: Time) => formatTehranChartTime(Number(time))      },
      grid: {
        vertLines: { color: "rgba(38, 47, 61, 0.42)" },
        horzLines: { color: "rgba(38, 47, 61, 0.42)" }
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "rgba(116, 139, 173, 0.72)",
          width: 1,
          labelBackgroundColor: "#263245"
        },
        horzLine: {
          color: "rgba(116, 139, 173, 0.72)",
          width: 1,
          labelBackgroundColor: "#263245"
        }
      },
      rightPriceScale: {
        borderColor: "#202936",
        scaleMargins: { top: 0.1, bottom: 0.1 },
        autoScale: true,
        minimumWidth: 72,
        tickMarkDensity: 2.8
      },
      timeScale: {
        borderColor: "#202936",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 12,
        barSpacing: 7,
        minBarSpacing: 1.2,
        maxBarSpacing: 48,
        fixLeftEdge: false,
        fixRightEdge: false,
        lockVisibleTimeRangeOnResize: true,
        rightBarStaysOnScroll: true,
        shiftVisibleRangeOnNewBar: true,
        uniformDistribution: true,
        enableConflation: true,
        conflationThresholdFactor: 1,
        precomputeConflationOnInit: false,
        precomputeConflationPriority: "background",
        tickMarkFormatter: (
  time: Time,
  tickMarkType: TickMarkType) => formatTehranChartTick(Number(time), tickMarkType)
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true
      }
    });

    this.candles = this.chart.addSeries(CandlestickSeries, {
      upColor: "#16c79a",
      downColor: "#ff6278",
      borderUpColor: "#16c79a",
      borderDownColor: "#ff6278",
      wickUpColor: "#4ad8b5",
      wickDownColor: "#ff8c9b",
      priceLineVisible: true,
      lastValueVisible: true,
      conflationThresholdFactor: 1
    });

    const notify = () => this.queueRender();
    this.chart.timeScale().subscribeVisibleLogicalRangeChange(notify);
    this.chart.timeScale().subscribeSizeChange(notify);
    this.resizeObserver = new ResizeObserver(notify);
    this.resizeObserver.observe(container);
  }

  destroy(): void {
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    if (this.renderFrame !== null) cancelAnimationFrame(this.renderFrame);
    this.renderFrame = null;
    this.lineSeries.clear();
    this.lineStates.clear();
    this.candles = null;
    this.chart?.remove();
    this.chart = null;
    this.barCount = 0;
    this.lastBarTime = null;
    this.priceViewportSignature = "";
    this.timeViewportSignature = "";
  }

  setBars(bars: ReplayBar[]): void {
    const data = normalizeCandleData(bars);
    this.candles?.setData(data);
    this.barCount = data.length;
    this.lastBarTime = data.at(-1)?.time ?? null;
    this.queueRender();
  }

  updateBars(bars: ReplayBar[]): void {
    if (bars.length === 0 || !this.candles) return;
    const data = normalizeCandleData(bars);
    for (const candle of data) {
      if (this.lastBarTime !== null && Number(candle.time) < Number(this.lastBarTime)) {
        throw new Error("Chart received out-of-order candle data");
      }
      this.candles.update(candle);
      if (this.lastBarTime === null || Number(candle.time) > Number(this.lastBarTime)) {
        this.barCount += 1;
      }
      this.lastBarTime = candle.time as UTCTimestamp;
    }
    this.queueRender();
  }

  setStrategyState(state: MaterializedChartState, tickSize: number): void {
    if (!this.chart) return;
    const active = new Set<string>();

    for (const definition of state.series.values()) {
      if (definition.kind !== "line") continue;
      active.add(definition.seriesId);
      const signature = `${definition.color}|${definition.lineWidth}|${definition.title}|${definition.visible}`;
      let series = this.lineSeries.get(definition.seriesId);
      if (!series) {
        series = this.chart.addSeries(LineSeries, {
          color: definition.color,
          lineWidth: normalizeLineWidth(definition.lineWidth),
          title: definition.title,
          visible: definition.visible,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: false,
          conflationThresholdFactor: 1.5
        });
        this.lineSeries.set(definition.seriesId, series);
      }

      const previous = this.lineStates.get(definition.seriesId);
      if (previous && previous.signature !== signature) {
        series.applyOptions({
          color: definition.color,
          lineWidth: normalizeLineWidth(definition.lineWidth),
          title: definition.title,
          visible: definition.visible
        });
      }

      const points = state.points.get(definition.seriesId) ?? [];
      const firstTimeNs = points[0]?.timeNs ?? null;
      const lastTimeNs = points.at(-1)?.timeNs ?? null;
      const requiresReplace =
        !previous ||
        points.length < previous.count ||
        previous.firstTimeNs !== firstTimeNs ||
        (previous.count > 0 && points[previous.count - 1]?.timeNs !== previous.lastTimeNs);

      if (requiresReplace) {
        series.setData(toNormalizedLineData(points, tickSize));
      } else {
        for (let index = previous.count; index < points.length; index += 1) {
          const point = points[index];
          if (!point || !Number.isFinite(point.timeNs) || !Number.isFinite(point.value)) continue;
          series.update(toLineData(point.timeNs, point.value, tickSize));
        }
      }

      this.lineStates.set(definition.seriesId, {
        count: points.length,
        firstTimeNs,
        lastTimeNs,
        signature
      });
    }

    for (const [seriesId, series] of this.lineSeries) {
      if (active.has(seriesId)) continue;
      this.chart.removeSeries(series);
      this.lineSeries.delete(seriesId);
      this.lineStates.delete(seriesId);
    }
    this.queueRender();
  }

  applyViewport(settings: ChartViewportSettings): void {
    const priceScale = this.candles?.priceScale();
    const priceSignature = settings.priceScaleMode === "locked" && settings.priceRange
      ? `locked:${settings.priceRange.from}:${settings.priceRange.to}`
      : "auto";

    if (priceSignature !== this.priceViewportSignature) {
      this.priceViewportSignature = priceSignature;
      if (settings.priceScaleMode === "locked" && settings.priceRange) {
        priceScale?.setAutoScale(false);
        priceScale?.setVisibleRange(settings.priceRange);
      } else {
        priceScale?.setAutoScale(true);
      }
    }

    const timeSignature = settings.followLatest
      ? `follow:${this.barCount}:${settings.barsVisible}:${settings.rightOffset}`
      : `free:${settings.lockTimeScale}:${settings.barsVisible}:${settings.rightOffset}`;
    if (timeSignature !== this.timeViewportSignature) {
      this.timeViewportSignature = timeSignature;
      if (settings.followLatest) {
        const range = latestLogicalRange(this.barCount, settings);
        if (range) this.chart?.timeScale().setVisibleLogicalRange(range);
      }
    }
    this.queueRender();
  }

  capturePriceRange(): PriceRange | null {
    const range = this.candles?.priceScale().getVisibleRange();
    if (!range || !Number.isFinite(range.from) || !Number.isFinite(range.to)) return null;
    return { from: range.from, to: range.to };
  }

  captureTimeViewport(): CapturedTimeViewport | null {
    const range = this.chart?.timeScale().getVisibleLogicalRange();
    if (!range || this.barCount <= 0) return null;
    const width = range.to - range.from;
    if (!Number.isFinite(width) || width <= 0) return null;
    return {
      barsVisible: Math.round(width),
      rightOffset: Math.max(0, Math.round(range.to - (this.barCount - 1)))
    };
  }

  fitContent(): void {
    this.chart?.timeScale().fitContent();
    this.queueRender();
  }

  coordinates(): ChartCoordinates {
    return {
      timeToX: timeNs =>
        this.chart?.timeScale().timeToCoordinate(timeNsToSeconds(timeNs) as UTCTimestamp) ?? null,
      priceToY: price => this.candles?.priceToCoordinate(price) ?? null
    };
  }

  subscribeRender(handler: () => void): () => void {
    this.renderHandlers.add(handler);
    return () => this.renderHandlers.delete(handler);
  }

  private queueRender(): void {
    if (this.renderFrame !== null) return;
    this.renderFrame = requestAnimationFrame(() => {
      this.renderFrame = null;
      for (const handler of this.renderHandlers) handler();
    });
  }
}

function normalizeCandleData(bars: ReplayBar[]): CandlestickData<UTCTimestamp>[] {
  const byTime = new Map<number, CandlestickData<UTCTimestamp>>();
  for (const bar of bars) {
    const candle = toCandleData(bar);
    if (!candle) continue;
    byTime.set(Number(candle.time), candle);
  }
  return [...byTime.values()].sort((left, right) => Number(left.time) - Number(right.time));
}

function toCandleData(bar: ReplayBar): CandlestickData<UTCTimestamp> | null {
  const time = timeNsToSeconds(bar.open_time_ns);
  const open = Number(bar.open);
  const high = Number(bar.high);
  const low = Number(bar.low);
  const close = Number(bar.close);
  if (![time, open, high, low, close].every(Number.isFinite)) return null;
  if (low > high || open < low || open > high || close < low || close > high) return null;
  return {
    time: time as UTCTimestamp,
    open,
    high,
    low,
    close
  };
}

function toNormalizedLineData(
  points: Array<{ timeNs: number; value: number }>,
  tickSize: number
): LineData<UTCTimestamp>[] {
  const byTime = new Map<number, LineData<UTCTimestamp>>();
  for (const point of points) {
    if (!Number.isFinite(point.timeNs) || !Number.isFinite(point.value)) continue;
    const data = toLineData(point.timeNs, point.value, tickSize);
    byTime.set(Number(data.time), data);
  }
  return [...byTime.values()].sort((left, right) => Number(left.time) - Number(right.time));
}

function toLineData(timeNs: number, value: number, tickSize: number): LineData<UTCTimestamp> {
  return {
    time: timeNsToSeconds(timeNs) as UTCTimestamp,
    value: value * tickSize
  };
}

function normalizeLineWidth(value: number): 1 | 2 | 3 | 4 {
  if (value <= 1) return 1;
  if (value === 2) return 2;
  if (value === 3) return 3;
  return 4;
}

const TEHRAN_CHART_DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZone: "Asia/Tehran",
  timeZoneName: "short"
});

const TEHRAN_CHART_YEAR = new Intl.DateTimeFormat("en-GB", {
  year: "numeric",
  timeZone: "Asia/Tehran"
});

const TEHRAN_CHART_MONTH = new Intl.DateTimeFormat("en-GB", {
  month: "short",
  timeZone: "Asia/Tehran"
});

const TEHRAN_CHART_DAY = new Intl.DateTimeFormat("en-GB", {
  month: "2-digit",
  day: "2-digit",
  timeZone: "Asia/Tehran"
});

const TEHRAN_CHART_TIME = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "Asia/Tehran"
});

function formatTehranChartTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return "—";
  return TEHRAN_CHART_DATE_TIME.format(new Date(seconds * 1_000)).replace(
    ",",
    ""
  );
}

function formatTehranChartTick(
  seconds: number,
  tickMarkType: TickMarkType
): string | null {
  if (!Number.isFinite(seconds)) return null;
  const date = new Date(seconds * 1_000);
  if (tickMarkType === TickMarkType.Year) return TEHRAN_CHART_YEAR.format(date);
  if (tickMarkType === TickMarkType.Month) return TEHRAN_CHART_MONTH.format(date);
  if (tickMarkType === TickMarkType.DayOfMonth) return TEHRAN_CHART_DAY.format(date);
  return TEHRAN_CHART_TIME.format(date);
}
