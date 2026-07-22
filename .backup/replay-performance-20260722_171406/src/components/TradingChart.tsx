import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import {
  AlertTriangle,
  Eye,
  EyeOff,
  Lock,
  Maximize2,
  Minimize2,
  RefreshCw,
  RotateCcw,
  Save,
  SlidersHorizontal,
  Unlock
} from "lucide-react";
import { LightweightChartsAdapter } from "../chart/LightweightChartsAdapter";
import { ReplayBarBuffer } from "../chart/ReplayBarBuffer";
import { DrawingViewportIndex } from "../chart/DrawingViewportIndex";
import type { VisibleTimeRangeNs } from "../chart/ChartAdapter";
import {
  CHART_BAR_COMPACTION_INTERVAL,
  CHART_BAR_WINDOW,
  MAX_VISIBLE_DRAWINGS
} from "../chart/performanceLimits";
import {
  brokerTradeIds,
  buildClosedTradeDrawings,
  buildOpenPositionDrawings
} from "../chart/brokerTradeDrawings";
import {
  applyChartCommandsMutable,
  cloneChartState,
  materializeChartState,
  type DrawingState,
  type MaterializedChartState
} from "../chart/chartState";
import {
  DEFAULT_CHART_VIEWPORT,
  loadViewportSettings,
  normalizeViewportSettings,
  saveViewportSettings,
  type ChartViewportSettings
} from "../chart/chartViewport";
import { formatNumber } from "../lib/format";
import type { FrameSchedulerStats } from "../lib/frameScheduler";
import type { ReplayRenderStream } from "../lib/replayRenderStream";
import type {
  PositionRecord,
  ReplayBar,
  ReplayBootstrap,
  ReplayFrame,
  TradeRecord
} from "../lib/types";
import {
  DrawingCanvasOverlay,
  type DrawingCanvasController,
  type DrawingRenderStats
} from "./DrawingCanvasOverlay";

interface Props {
  bars: ReplayBar[];
  chartState: MaterializedChartState;
  tickSize: number;
  symbol: string;
  timeframe: string;
  focused: boolean;
  diagnosticsVisible: boolean;
  frameStats: FrameSchedulerStats;
  renderStream: ReplayRenderStream;
  trades: TradeRecord[];
  positions: PositionRecord[];
  onFocusToggle: () => void;
}

interface IndicatorLegendEntry {
  id: string;
  title: string;
  color: string;
  value: number | undefined;
}

interface ChartHudState {
  lastBar: ReplayBar | null;
  visibleBars: number;
  pointCount: number;
  drawingCount: number;
  indicatorLegend: IndicatorLegendEntry[];
}

const HUD_REFRESH_MS = 250;
const MAX_AUTOMATIC_RECOVERIES = 3;
const RECOVERY_WINDOW_MS = 30_000;
const BAR_OPTIONS = [60, 100, 160, 240, 400, 800];
const EMPTY_DRAWING_STATS: DrawingRenderStats = {
  totalDrawings: 0,
  matchedDrawings: 0,
  renderedDrawings: 0,
  primitiveCount: 0,
  buildTimeMs: 0
};

export const TradingChart = memo(function TradingChart({
  bars,
  chartState,
  tickSize,
  symbol,
  timeframe,
  focused,
  diagnosticsVisible,
  frameStats,
  renderStream,
  trades,
  positions,
  onFocusToggle
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const adapterRef = useRef<LightweightChartsAdapter | null>(null);
  const overlayRef = useRef<DrawingCanvasController | null>(null);
  const barBufferRef = useRef(new ReplayBarBuffer(CHART_BAR_WINDOW, bars));
  const chartModelRef = useRef(cloneChartState(chartState));
  const viewportRef = useRef<ChartViewportSettings>(loadViewportSettings(symbol, timeframe));
  const indicatorsVisibleRef = useRef(true);
  const appendedSinceCompactionRef = useRef(0);
  const hudTimerRef = useRef<number | null>(null);
  const renderCounterRef = useRef(0);
  const recoveriesRef = useRef<number[]>([]);
  const recoveryTimerRef = useRef<number | null>(null);
  const activeIdentityRef = useRef(`${symbol}:${timeframe}`);
  const closedBrokerDrawingsRef = useRef<DrawingState[]>([]);
  const openBrokerDrawingsRef = useRef<DrawingState[]>([]);
  const representedTradeIdsRef = useRef(new Set<string>());
  const closedTradeSignatureRef = useRef("");
  const openPositionSignatureRef = useRef("");
  const drawingIndexRef = useRef(new DrawingViewportIndex());
  const tradesRef = useRef(trades);
  const positionsRef = useRef(positions);

  const [adapter, setAdapter] = useState<LightweightChartsAdapter | null>(null);
  const [adapterGeneration, setAdapterGeneration] = useState(0);
  const [chartIssue, setChartIssue] = useState<string | null>(null);
  const [chartRecoveryBlocked, setChartRecoveryBlocked] = useState(false);
  const [fps, setFps] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [drawingStats, setDrawingStats] = useState<DrawingRenderStats>(EMPTY_DRAWING_STATS);
  const [indicatorsVisible, setIndicatorsVisible] = useState(true);
  const [viewport, setViewport] = useState<ChartViewportSettings>(() =>
    loadViewportSettings(symbol, timeframe)
  );
  const [hud, setHud] = useState<ChartHudState>(() => createHudState(
    barBufferRef.current,
    chartModelRef.current,
    true
  ));

  indicatorsVisibleRef.current = indicatorsVisible;
  viewportRef.current = viewport;
  activeIdentityRef.current = `${symbol}:${timeframe}`;
  tradesRef.current = trades;
  positionsRef.current = positions;

  const getDrawings = useCallback((range: VisibleTimeRangeNs | null) => {
    const openDrawings = openBrokerDrawingsRef.current;
    const staticLimit = Math.max(1, MAX_VISIBLE_DRAWINGS - openDrawings.length);
    const indexed = drawingIndexRef.current.query(range, staticLimit);
    const visibleOpen = openDrawings.length <= MAX_VISIBLE_DRAWINGS
      ? openDrawings
      : openDrawings.slice(-MAX_VISIBLE_DRAWINGS);
    return {
      drawings: [...indexed.drawings, ...visibleOpen],
      totalCount: indexed.totalCount + openDrawings.length,
      matchedCount: indexed.matchedCount + openDrawings.length
    };
  }, []);

  const getLatestTimeNs = useCallback(
    () => barBufferRef.current.last?.close_time_ns ?? null,
    []
  );

  const rebuildDrawingIndex = useCallback(() => {
    const representedTradeIds = representedTradeIdsRef.current;
    const drawings: DrawingState[] = [];
    for (const drawing of chartModelRef.current.drawings.values()) {
      const payload = drawing.payload;
      const isSupersededTradeBox =
        payload.kind === "risk_reward" &&
        representedTradeIds.has(String(payload.trade_id ?? ""));
      if (!isSupersededTradeBox) drawings.push(drawing);
    }
    drawings.push(...closedBrokerDrawingsRef.current);
    drawingIndexRef.current.replace(drawings);
  }, []);

  const refreshBrokerDrawings = useCallback((force = false) => {
    const nextClosedSignature = closedTradeSignature(tradesRef.current, symbol);
    if (force || nextClosedSignature !== closedTradeSignatureRef.current) {
      closedTradeSignatureRef.current = nextClosedSignature;
      const closedDrawings = buildClosedTradeDrawings(symbol, tradesRef.current);
      closedBrokerDrawingsRef.current = closedDrawings;
      representedTradeIdsRef.current = brokerTradeIds(closedDrawings);
      rebuildDrawingIndex();
    }

    const nextOpenSignature = openPositionSignature(positionsRef.current, symbol);
    if (force || nextOpenSignature !== openPositionSignatureRef.current) {
      openPositionSignatureRef.current = nextOpenSignature;
      openBrokerDrawingsRef.current = buildOpenPositionDrawings(symbol, positionsRef.current);
    }
  }, [rebuildDrawingIndex, symbol]);

  const scheduleHudRefresh = useCallback((immediate = false) => {
    if (immediate) {
      if (hudTimerRef.current !== null) window.clearTimeout(hudTimerRef.current);
      hudTimerRef.current = null;
      setHud(createHudState(
        barBufferRef.current,
        chartModelRef.current,
        indicatorsVisibleRef.current
      ));
      return;
    }
    if (hudTimerRef.current !== null) return;
    hudTimerRef.current = window.setTimeout(() => {
      hudTimerRef.current = null;
      setHud(createHudState(
        barBufferRef.current,
        chartModelRef.current,
        indicatorsVisibleRef.current
      ));
    }, HUD_REFRESH_MS);
  }, []);

  const requestRecovery = useCallback((operation: string, error: unknown) => {
    const message = `${operation}: ${formatError(error)}`;
    console.error("VEX chart operation failed", { operation, error });
    setChartIssue(message);

    const now = Date.now();
    recoveriesRef.current = recoveriesRef.current.filter(
      timestamp => now - timestamp <= RECOVERY_WINDOW_MS
    );
    if (recoveriesRef.current.length >= MAX_AUTOMATIC_RECOVERIES) {
      setChartRecoveryBlocked(true);
      return;
    }
    recoveriesRef.current.push(now);
    if (recoveryTimerRef.current !== null) return;
    recoveryTimerRef.current = window.setTimeout(() => {
      recoveryTimerRef.current = null;
      setAdapterGeneration(value => value + 1);
    }, 120);
  }, []);

  const runChartOperation = useCallback((operation: string, callback: () => void) => {
    try {
      callback();
    } catch (error) {
      requestRecovery(operation, error);
    }
  }, [requestRecovery]);

  const applyCurrentViewport = useCallback(() => {
    runChartOperation("apply viewport", () => {
      adapterRef.current?.applyViewport(viewportRef.current);
    });
  }, [runChartOperation]);

  const resetFromBootstrap = useCallback((bootstrap: ReplayBootstrap) => {
    if (`${bootstrap.symbol}:${bootstrap.timeframe}` !== activeIdentityRef.current) return;
    barBufferRef.current.replace(bootstrap.bars);
    chartModelRef.current = materializeChartState(bootstrap.timeline);
    appendedSinceCompactionRef.current = 0;
    refreshBrokerDrawings(true);

    runChartOperation("reset chart", () => {
      const currentAdapter = adapterRef.current;
      if (!currentAdapter) return;
      currentAdapter.setBars(barBufferRef.current.toArray());
      currentAdapter.setStrategyState(
        indicatorsVisibleRef.current
          ? chartModelRef.current
          : withoutIndicatorSeries(chartModelRef.current),
        tickSize
      );
      currentAdapter.applyViewport(viewportRef.current);
    });
    overlayRef.current?.invalidate();
    scheduleHudRefresh(true);
  }, [refreshBrokerDrawings, runChartOperation, scheduleHudRefresh, tickSize]);

  const applyAdvanceFrame = useCallback((frame: ReplayFrame) => {
    const appendResult = barBufferRef.current.append(frame.bars);
    const mutation = applyChartCommandsMutable(chartModelRef.current, frame.timeline);

    runChartOperation("apply replay frame", () => {
      const currentAdapter = adapterRef.current;
      if (!currentAdapter) return;

      if (appendResult.rebuildRequired) {
        currentAdapter.setBars(barBufferRef.current.toArray());
        appendedSinceCompactionRef.current = 0;
      } else {
        if (appendResult.replacedLast) {
          currentAdapter.updateBars([appendResult.replacedLast]);
        }
        if (appendResult.appended.length > 0) {
          currentAdapter.updateBars(appendResult.appended);
          appendedSinceCompactionRef.current += appendResult.appended.length;
        }
        if (
          appendResult.windowShifted &&
          appendedSinceCompactionRef.current >= CHART_BAR_COMPACTION_INTERVAL
        ) {
          currentAdapter.setBars(barBufferRef.current.toArray());
          appendedSinceCompactionRef.current = 0;
        }
      }

      if (mutation.seriesChanged || mutation.seriesPoints > 0) {
        currentAdapter.setStrategyState(
          indicatorsVisibleRef.current
            ? chartModelRef.current
            : withoutIndicatorSeries(chartModelRef.current),
          tickSize
        );
      }
    });

    if (mutation.drawingsChanged) {
      rebuildDrawingIndex();
      overlayRef.current?.invalidate();
    }
    scheduleHudRefresh();
  }, [rebuildDrawingIndex, runChartOperation, scheduleHudRefresh, tickSize]);

  const applyResetFrame = useCallback((frame: ReplayFrame) => {
    barBufferRef.current.replace(frame.bars);
    applyChartCommandsMutable(chartModelRef.current, frame.timeline);
    appendedSinceCompactionRef.current = 0;
    refreshBrokerDrawings(true);

    runChartOperation("apply visual reset", () => {
      const currentAdapter = adapterRef.current;
      if (!currentAdapter) return;
      currentAdapter.setBars(barBufferRef.current.toArray());
      currentAdapter.setStrategyState(
        indicatorsVisibleRef.current
          ? chartModelRef.current
          : withoutIndicatorSeries(chartModelRef.current),
        tickSize
      );
      currentAdapter.applyViewport(viewportRef.current);
    });

    overlayRef.current?.invalidate();
    scheduleHudRefresh(true);
  }, [refreshBrokerDrawings, runChartOperation, scheduleHudRefresh, tickSize]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const onContextLost = (event: Event) => {
      event.preventDefault();
      requestRecovery("canvas context lost", new Error("The browser renderer lost its canvas context"));
    };
    container.addEventListener("contextlost", onContextLost, true);

    const nextAdapter = new LightweightChartsAdapter();
    try {
      nextAdapter.mount(container);
      nextAdapter.setBars(barBufferRef.current.toArray());
      nextAdapter.setStrategyState(
        indicatorsVisibleRef.current
          ? chartModelRef.current
          : withoutIndicatorSeries(chartModelRef.current),
        tickSize
      );
      nextAdapter.applyViewport(viewportRef.current);
      adapterRef.current = nextAdapter;
      setAdapter(nextAdapter);
      setChartIssue(null);
      setChartRecoveryBlocked(false);
    } catch (error) {
      container.removeEventListener("contextlost", onContextLost, true);
      nextAdapter.destroy();
      requestRecovery("mount chart", error);
      return;
    }

    const unsubscribe = nextAdapter.subscribeRender(() => {
      renderCounterRef.current += 1;
    });

    return () => {
      unsubscribe();
      container.removeEventListener("contextlost", onContextLost, true);
      nextAdapter.destroy();
      if (adapterRef.current === nextAdapter) adapterRef.current = null;
      setAdapter(current => current === nextAdapter ? null : current);
    };
  }, [adapterGeneration, requestRecovery, tickSize]);

  useEffect(() => {
    const unsubscribe = renderStream.subscribe(message => {
      if (message.type === "bootstrap") {
        resetFromBootstrap(message.data);
        return;
      }
      if (message.type !== "frame") return;
      if (message.data.frame_type === "reset") {
        applyResetFrame(message.data);
        return;
      }
      if (
        message.data.frame_type === "advance" ||
        message.data.frame_type === "completed"
      ) {
        applyAdvanceFrame(message.data);
      }
    });
    return unsubscribe;
  }, [applyAdvanceFrame, applyResetFrame, renderStream, resetFromBootstrap]);

  useEffect(() => {
    const nextIdentity = `${symbol}:${timeframe}`;
    activeIdentityRef.current = nextIdentity;
    barBufferRef.current.replace(bars);
    chartModelRef.current = cloneChartState(chartState);
    appendedSinceCompactionRef.current = 0;
    setDrawingStats(EMPTY_DRAWING_STATS);
    refreshBrokerDrawings(true);
    const nextViewport = loadViewportSettings(symbol, timeframe);
    viewportRef.current = nextViewport;
    setViewport(nextViewport);

    runChartOperation("switch chart series", () => {
      adapterRef.current?.setBars(barBufferRef.current.toArray());
      adapterRef.current?.setStrategyState(
        indicatorsVisibleRef.current
          ? chartModelRef.current
          : withoutIndicatorSeries(chartModelRef.current),
        tickSize
      );
      adapterRef.current?.applyViewport(nextViewport);
    });
    overlayRef.current?.invalidate();
    scheduleHudRefresh(true);
  }, [symbol, timeframe, tickSize, refreshBrokerDrawings, runChartOperation, scheduleHudRefresh]);


  useEffect(() => {
    refreshBrokerDrawings();
    overlayRef.current?.invalidate();
    scheduleHudRefresh();
  }, [positions, refreshBrokerDrawings, scheduleHudRefresh, trades]);

  useEffect(() => {
    if (!diagnosticsVisible) {
      setFps(0);
      return;
    }
    let previous = renderCounterRef.current;
    const timer = window.setInterval(() => {
      const current = renderCounterRef.current;
      setFps(current - previous);
      previous = current;
    }, 1000);
    return () => window.clearInterval(timer);
  }, [diagnosticsVisible]);

  useEffect(() => {
    const normalized = normalizeViewportSettings(viewport);
    viewportRef.current = normalized;
    saveViewportSettings(symbol, timeframe, normalized);
    applyCurrentViewport();
  }, [symbol, timeframe, viewport, applyCurrentViewport]);

  useEffect(() => {
    runChartOperation("toggle indicators", () => {
      adapterRef.current?.setStrategyState(
        indicatorsVisible
          ? chartModelRef.current
          : withoutIndicatorSeries(chartModelRef.current),
        tickSize
      );
    });
    scheduleHudRefresh(true);
  }, [indicatorsVisible, tickSize, runChartOperation, scheduleHudRefresh]);

  useEffect(() => () => {
    if (hudTimerRef.current !== null) window.clearTimeout(hudTimerRef.current);
    if (recoveryTimerRef.current !== null) window.clearTimeout(recoveryTimerRef.current);
  }, []);

  const ohlc = useMemo(() => {
    const lastBar = hud.lastBar;
    if (!lastBar) return null;
    const open = Number(lastBar.open);
    const close = Number(lastBar.close);
    const change = open === 0 ? 0 : ((close - open) / open) * 100;
    return {
      open,
      high: Number(lastBar.high),
      low: Number(lastBar.low),
      close,
      change
    };
  }, [hud.lastBar]);

  const updateViewport = (patch: Partial<ChartViewportSettings>) => {
    setViewport(current => normalizeViewportSettings({ ...current, ...patch }));
  };

  const toggleTimeLock = () => {
    if (viewport.lockTimeScale) {
      updateViewport({ lockTimeScale: false });
      return;
    }
    const captured = adapterRef.current?.captureTimeViewport() ?? null;
    updateViewport({ lockTimeScale: true, ...(captured ?? {}) });
  };

  const captureTimeLock = () => {
    const captured = adapterRef.current?.captureTimeViewport() ?? null;
    if (captured) updateViewport(captured);
  };

  const togglePriceLock = () => {
    if (viewport.priceScaleMode === "locked") {
      updateViewport({ priceScaleMode: "auto", priceRange: null });
      return;
    }
    const range = adapterRef.current?.capturePriceRange() ?? null;
    if (range) updateViewport({ priceScaleMode: "locked", priceRange: range });
  };

  const capturePriceLock = () => {
    const range = adapterRef.current?.capturePriceRange() ?? null;
    if (range) updateViewport({ priceScaleMode: "locked", priceRange: range });
  };

  const resetViewport = () => {
    setViewport(DEFAULT_CHART_VIEWPORT);
    runChartOperation("reset viewport", () => {
      adapterRef.current?.fitContent();
      window.setTimeout(() => adapterRef.current?.applyViewport(DEFAULT_CHART_VIEWPORT), 0);
    });
  };

  const retryChart = () => {
    recoveriesRef.current = [];
    setChartRecoveryBlocked(false);
    setChartIssue(null);
    setAdapterGeneration(value => value + 1);
  };

  return (
    <section className="chart-shell" aria-label={`${symbol} ${timeframe} replay chart`}>
      <div className="chart-head-up-display">
        <div className="instrument-heading">
          <strong>{symbol}</strong>
          <span>{timeframe}</span>
          <span className="market-source">MT5 · Bid candles</span>
        </div>
        {ohlc ? (
          <div className="ohlc-strip">
            <span>O <strong>{formatNumber(ohlc.open)}</strong></span>
            <span>H <strong>{formatNumber(ohlc.high)}</strong></span>
            <span>L <strong>{formatNumber(ohlc.low)}</strong></span>
            <span>C <strong>{formatNumber(ohlc.close)}</strong></span>
            <span className={ohlc.change >= 0 ? "positive" : "negative"}>
              {ohlc.change >= 0 ? "+" : ""}{ohlc.change.toFixed(3)}%
            </span>
          </div>
        ) : null}
        <div className="indicator-legend">
          {hud.indicatorLegend.map(indicator => (
            <span key={indicator.id} style={{ "--series-color": indicator.color } as React.CSSProperties}>
              <i /> {indicator.title}
              {indicator.value !== undefined
                ? <strong>{formatNumber(indicator.value * tickSize)}</strong>
                : null}
            </span>
          ))}
        </div>
      </div>

      <div className={`chart-control-panel ${settingsOpen ? "expanded" : ""}`}>
        <button
          className="chart-control-trigger"
          onClick={() => setSettingsOpen(value => !value)}
          title="Chart viewport controls"
        >
          <SlidersHorizontal size={14} />
        </button>
        <div className="chart-control-content">
          <label>
            <span>Visible</span>
            <select
              value={viewport.barsVisible}
              onChange={(event: React.ChangeEvent<HTMLSelectElement>) =>
                updateViewport({ barsVisible: Number(event.target.value) })}
            >
              {BAR_OPTIONS.map(value => <option key={value} value={value}>{value} bars</option>)}
            </select>
          </label>
          <button
            className={viewport.followLatest ? "active" : ""}
            onClick={() => updateViewport({ followLatest: !viewport.followLatest })}
            title="Keep the newest candle at the right edge"
          >
            Follow
          </button>
          <button
            className={viewport.lockTimeScale ? "active" : ""}
            onClick={toggleTimeLock}
            title="Keep horizontal zoom stable"
          >
            {viewport.lockTimeScale ? <Lock size={13} /> : <Unlock size={13} />} X
          </button>
          {viewport.lockTimeScale
            ? <button onClick={captureTimeLock} title="Capture current horizontal range"><Save size={13} /></button>
            : null}
          <button
            className={viewport.priceScaleMode === "locked" ? "active" : ""}
            onClick={togglePriceLock}
            title="Keep vertical price range stable"
          >
            {viewport.priceScaleMode === "locked" ? <Lock size={13} /> : <Unlock size={13} />} Y
          </button>
          {viewport.priceScaleMode === "locked"
            ? <button onClick={capturePriceLock} title="Capture current price range"><Save size={13} /></button>
            : null}
          <button
            className={indicatorsVisible ? "active" : ""}
            onClick={() => setIndicatorsVisible(value => !value)}
            title="Toggle strategy indicator series"
          >
            {indicatorsVisible ? <Eye size={13} /> : <EyeOff size={13} />} Studies
          </button>
          <button onClick={resetViewport} title="Reset viewport"><RotateCcw size={13} /></button>
          <button onClick={onFocusToggle} title={focused ? "Exit chart focus" : "Maximize chart"}>
            {focused ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </div>

      <div className="chart-container" ref={containerRef} />
      {adapter ? (
        <DrawingCanvasOverlay
          ref={overlayRef}
          adapter={adapter}
          getDrawings={getDrawings}
          getLatestTimeNs={getLatestTimeNs}
          tickSize={tickSize}
          {...(diagnosticsVisible ? { onStats: setDrawingStats } : {})}
        />
      ) : null}

      {chartIssue ? (
        <div className={`chart-recovery-notice ${chartRecoveryBlocked ? "blocked" : ""}`}>
          <AlertTriangle size={15} />
          <div>
            <strong>{chartRecoveryBlocked ? "Chart paused after repeated renderer failures" : "Chart renderer recovered"}</strong>
            <span>{chartIssue}</span>
          </div>
          {chartRecoveryBlocked ? (
            <button onClick={retryChart}><RefreshCw size={13} /> Retry chart</button>
          ) : null}
        </div>
      ) : null}

      {diagnosticsVisible ? (
        <div className="performance-hud">
          <div><span>Chart FPS</span><strong>{fps}</strong></div>
          <div><span>Bars</span><strong>{hud.visibleBars.toLocaleString()}</strong></div>
          <div><span>Study points</span><strong>{hud.pointCount.toLocaleString()}</strong></div>
          <div><span>Drawings total</span><strong>{drawingStats.totalDrawings.toLocaleString()}</strong></div>
          <div><span>Drawings visible</span><strong>{drawingStats.renderedDrawings.toLocaleString()}</strong></div>
          <div><span>Overlay primitives</span><strong>{drawingStats.primitiveCount.toLocaleString()}</strong></div>
          <div><span>Overlay build</span><strong>{drawingStats.buildTimeMs.toFixed(1)} ms</strong></div>
          <div><span>Socket batch</span><strong>{frameStats.lastBatchSize}</strong></div>
          <div><span>Merged frames</span><strong>{frameStats.mergedFrames.toLocaleString()}</strong></div>
          <div><span>Replay thread</span><strong>{frameStats.executionMode}</strong></div>
          <div><span>Resyncs</span><strong>{frameStats.resyncs}</strong></div>
        </div>
      ) : null}
    </section>
  );
});

function createHudState(
  buffer: ReplayBarBuffer,
  chartState: MaterializedChartState,
  indicatorsVisible: boolean
): ChartHudState {
  const indicatorLegend = indicatorsVisible
    ? [...chartState.series.values()]
        .filter(series => series.kind === "line" && series.visible)
        .map(series => ({
          id: series.seriesId,
          title: series.title,
          color: series.color,
          value: chartState.points.get(series.seriesId)?.at(-1)?.value
        }))
        .slice(0, 6)
    : [];

  let pointCount = 0;
  for (const points of chartState.points.values()) pointCount += points.length;

  return {
    lastBar: buffer.last,
    visibleBars: buffer.size,
    pointCount,
    drawingCount: chartState.drawings.size,
    indicatorLegend
  };
}

function withoutIndicatorSeries(state: MaterializedChartState): MaterializedChartState {
  return {
    series: new Map(),
    points: new Map(),
    drawings: state.drawings
  };
}

function closedTradeSignature(trades: TradeRecord[], symbol: string): string {
  const recent: string[] = [];
  for (let index = trades.length - 1; index >= 0 && recent.length < 3; index -= 1) {
    const trade = trades[index];
    if (!trade || trade.symbol !== symbol) continue;
    recent.push(`${trade.trade_id}:${trade.exit_time_ns}:${trade.net_pnl}:${trade.exit_reason}`);
  }
  return `${symbol}:${trades.length}:${recent.join("|")}`;
}

function openPositionSignature(positions: PositionRecord[], symbol: string): string {
  const matching = positions
    .filter(position => position.symbol === symbol)
    .map(position => [
      position.position_id,
      position.status,
      position.opened_time_ns,
      position.current_price_ticks,
      position.stop_loss_ticks,
      position.take_profit_ticks,
      position.unrealized_pnl
    ].join(":"))
    .sort();
  return `${symbol}:${matching.join("|")}`;
}

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
