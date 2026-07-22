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
  CHART_HISTORY_FETCH_COUNT,
  CHART_HISTORY_FETCH_DEBOUNCE_MS,
  CHART_HISTORY_PREFETCH_RATIO,
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
  pruneChartStateToWindow,
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
import { fetchReplayWindow } from "../lib/api";
import { formatNumber } from "../lib/format";
import type { FrameSchedulerStats } from "../lib/frameScheduler";
import type { ReplayRenderStream } from "../lib/replayRenderStream";
import type {
  PositionRecord,
  ReplayBar,
  ReplayBootstrap,
  ReplayFrame,
  Timeframe,
  TradeRecord
} from "../lib/types";
import {
  DrawingCanvasOverlay,
  type DrawingCanvasController,
  type DrawingRenderStats
} from "./DrawingCanvasOverlay";

interface Props {
  runId: string;
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
const ACTIVE_WINDOW_MAINTENANCE_INTERVAL = 256;
const EMPTY_DRAWING_STATS: DrawingRenderStats = {
  totalDrawings: 0,
  matchedDrawings: 0,
  renderedDrawings: 0,
  primitiveCount: 0,
  buildTimeMs: 0
};

export const TradingChart = memo(function TradingChart({
  runId,
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
  const liveBarBufferRef = useRef(new ReplayBarBuffer(CHART_BAR_WINDOW, bars));
  const chartModelRef = useRef(cloneChartState(chartState));
  const liveChartModelRef = useRef(cloneChartState(chartState));
  const viewportRef = useRef<ChartViewportSettings>(loadViewportSettings(symbol, timeframe));
  const indicatorsVisibleRef = useRef(true);
  const appendedSinceCompactionRef = useRef(0);
  const activeWindowBucketRef = useRef<number | null>(null);
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
  const browsingHistoryRef = useRef(false);
  const historyFetchTimerRef = useRef<number | null>(null);
  const historyAbortRef = useRef<AbortController | null>(null);
  const historyRequestKeyRef = useRef("");
  const historyLoadingRef = useRef(false);
  const historyStartReachedRef = useRef(false);
  const viewportHandlerRef = useRef<() => void>(() => undefined);

  const [adapter, setAdapter] = useState<LightweightChartsAdapter | null>(null);
  const [adapterGeneration, setAdapterGeneration] = useState(0);
  const [chartIssue, setChartIssue] = useState<string | null>(null);
  const [chartRecoveryBlocked, setChartRecoveryBlocked] = useState(false);
  const [fps, setFps] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [drawingStats, setDrawingStats] = useState<DrawingRenderStats>(EMPTY_DRAWING_STATS);
  const [indicatorsVisible, setIndicatorsVisible] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyMode, setHistoryMode] = useState(false);
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
    () => (browsingHistoryRef.current ? barBufferRef.current : liveBarBufferRef.current).last?.open_time_ns ?? null,
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
    const activeBuffer = browsingHistoryRef.current
      ? barBufferRef.current
      : liveBarBufferRef.current;
    const first = activeBuffer.first;
    const last = activeBuffer.last;
    const windowedTrades = filterTradesForWindow(
      tradesRef.current,
      symbol,
      first?.open_time_ns ?? null,
      last?.close_time_ns ?? null
    );
    const windowKey = first
      ? String(Math.floor(first.sequence / ACTIVE_WINDOW_MAINTENANCE_INTERVAL))
      : "none";
    const nextClosedSignature = closedTradeSignature(windowedTrades, symbol, windowKey);
    if (force || nextClosedSignature !== closedTradeSignatureRef.current) {
      closedTradeSignatureRef.current = nextClosedSignature;
      const closedDrawings = buildClosedTradeDrawings(symbol, windowedTrades);
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

  const pruneLiveChartState = useCallback(() => {
    return pruneChartStateForBuffer(
      liveChartModelRef.current,
      liveBarBufferRef.current
    );
  }, []);

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

  const restoreLatestWindow = useCallback(() => {
    historyAbortRef.current?.abort();
    historyAbortRef.current = null;
    historyRequestKeyRef.current = "";
    historyLoadingRef.current = false;
    historyStartReachedRef.current = false;
    browsingHistoryRef.current = false;
    setHistoryMode(false);
    setHistoryLoading(false);
    pruneLiveChartState();
    barBufferRef.current.replace(liveBarBufferRef.current.toArray());
    chartModelRef.current = liveChartModelRef.current;
    appendedSinceCompactionRef.current = 0;
    activeWindowBucketRef.current = liveBarBufferRef.current.first
      ? Math.floor(liveBarBufferRef.current.first.sequence / ACTIVE_WINDOW_MAINTENANCE_INTERVAL)
      : null;
    refreshBrokerDrawings(true);
    runChartOperation("restore latest chart window", () => {
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
  }, [pruneLiveChartState, refreshBrokerDrawings, runChartOperation, scheduleHudRefresh, tickSize]);

  const loadHistoricalWindow = useCallback(async () => {
    if (
      !browsingHistoryRef.current ||
      historyLoadingRef.current ||
      historyStartReachedRef.current
    ) return;

    const currentBars = barBufferRef.current.toArray();
    const currentAdapter = adapterRef.current;
    if (currentBars.length < 2 || !currentAdapter) return;

    const shiftCount = Math.min(
      CHART_HISTORY_FETCH_COUNT,
      Math.max(1, currentBars.length - 1)
    );
    const targetIndex = Math.max(0, currentBars.length - shiftCount - 1);
    const target = currentBars[targetIndex];
    if (!target) return;

    const requestKey = `${runId}:${symbol}:${timeframe}:${target.close_time_ns}`;
    if (historyRequestKeyRef.current === requestKey) return;
    historyRequestKeyRef.current = requestKey;
    historyAbortRef.current?.abort();
    const controller = new AbortController();
    historyAbortRef.current = controller;
    historyLoadingRef.current = true;
    setHistoryLoading(true);
    const preservedRange = currentAdapter.visibleTimeRangeNs();
    const previousFirstSequence = currentBars[0]?.sequence ?? null;

    try {
      const snapshot = await fetchReplayWindow(
        runId,
        symbol,
        timeframe as Timeframe,
        target.close_time_ns,
        CHART_BAR_WINDOW,
        controller.signal
      );
      if (controller.signal.aborted || !browsingHistoryRef.current) return;
      if (`${snapshot.symbol}:${snapshot.timeframe}` !== activeIdentityRef.current) return;

      const nextBars = snapshot.bars.slice(-CHART_BAR_WINDOW);
      const nextFirstSequence = nextBars[0]?.sequence ?? null;
      if (
        nextBars.length === 0 ||
        nextFirstSequence === null ||
        (previousFirstSequence !== null && nextFirstSequence >= previousFirstSequence)
      ) {
        historyStartReachedRef.current = true;
        return;
      }

      barBufferRef.current.replace(nextBars);
      chartModelRef.current = materializeChartState(snapshot.timeline);
      pruneChartStateForBuffer(chartModelRef.current, barBufferRef.current);
      const historicalTrades = filterTradesForWindow(
        snapshot.trades,
        symbol,
        barBufferRef.current.first?.open_time_ns ?? null,
        barBufferRef.current.last?.close_time_ns ?? null
      );
      const historicalClosed = buildClosedTradeDrawings(symbol, historicalTrades);
      closedBrokerDrawingsRef.current = historicalClosed;
      openBrokerDrawingsRef.current = buildOpenPositionDrawings(
        symbol,
        snapshot.positions
      );
      representedTradeIdsRef.current = brokerTradeIds(historicalClosed);
      closedTradeSignatureRef.current = closedTradeSignature(
        historicalTrades,
        symbol,
        `${barBufferRef.current.first?.sequence ?? "none"}:${barBufferRef.current.last?.sequence ?? "none"}`
      );
      openPositionSignatureRef.current = openPositionSignature(
        snapshot.positions,
        symbol
      );
      rebuildDrawingIndex();
      appendedSinceCompactionRef.current = 0;

      runChartOperation("load historical chart window", () => {
        const adapter = adapterRef.current;
        if (!adapter) return;
        adapter.setBars(barBufferRef.current.toArray());
        adapter.setStrategyState(
          indicatorsVisibleRef.current
            ? chartModelRef.current
            : withoutIndicatorSeries(chartModelRef.current),
          tickSize
        );
        if (preservedRange) adapter.setVisibleTimeRangeNs(preservedRange);
      });
      overlayRef.current?.invalidate();
      scheduleHudRefresh(true);
    } catch (error) {
      if (!controller.signal.aborted) {
        requestRecovery("load historical chart window", error);
      }
    } finally {
      if (historyAbortRef.current === controller) historyAbortRef.current = null;
      historyLoadingRef.current = false;
      historyRequestKeyRef.current = "";
      setHistoryLoading(false);
    }
  }, [
    rebuildDrawingIndex,
    requestRecovery,
    runChartOperation,
    runId,
    scheduleHudRefresh,
    symbol,
    tickSize,
    timeframe
  ]);

  const handleViewportChanged = useCallback(() => {
    if (historyFetchTimerRef.current !== null) {
      window.clearTimeout(historyFetchTimerRef.current);
    }
    historyFetchTimerRef.current = window.setTimeout(() => {
      historyFetchTimerRef.current = null;
      const currentAdapter = adapterRef.current;
      const range = currentAdapter?.visibleTimeRangeNs() ?? null;
      const first = barBufferRef.current.first;
      const latest = liveBarBufferRef.current.last;
      if (!range || !first || !latest) return;
      const span = Math.max(1, range.to - range.from);
      const detachThreshold = Math.max(span * 0.2, 60_000_000_000);
      const detached = range.to < latest.close_time_ns - detachThreshold;
      if (detached && !browsingHistoryRef.current) {
        browsingHistoryRef.current = true;
        historyStartReachedRef.current = false;
        setHistoryMode(true);
        setViewport(current => current.followLatest ? { ...current, followLatest: false } : current);
      }
      if (!browsingHistoryRef.current || historyStartReachedRef.current) return;
      const prefetchBoundary = first.close_time_ns + span * CHART_HISTORY_PREFETCH_RATIO;
      if (range.from <= prefetchBoundary) void loadHistoricalWindow();
    }, CHART_HISTORY_FETCH_DEBOUNCE_MS);
  }, [loadHistoricalWindow]);

  viewportHandlerRef.current = handleViewportChanged;

  const resetFromBootstrap = useCallback((bootstrap: ReplayBootstrap) => {
    if (`${bootstrap.symbol}:${bootstrap.timeframe}` !== activeIdentityRef.current) return;
    historyAbortRef.current?.abort();
    historyAbortRef.current = null;
    historyRequestKeyRef.current = "";
    historyLoadingRef.current = false;
    historyStartReachedRef.current = false;
    browsingHistoryRef.current = false;
    setHistoryMode(false);
    setHistoryLoading(false);
    liveBarBufferRef.current.replace(bootstrap.bars);
    barBufferRef.current.replace(bootstrap.bars);
    liveChartModelRef.current = materializeChartState(bootstrap.timeline);
    pruneChartStateForBuffer(liveChartModelRef.current, liveBarBufferRef.current);
    chartModelRef.current = liveChartModelRef.current;
    appendedSinceCompactionRef.current = 0;
    activeWindowBucketRef.current = liveBarBufferRef.current.first
      ? Math.floor(liveBarBufferRef.current.first.sequence / ACTIVE_WINDOW_MAINTENANCE_INTERVAL)
      : null;
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
    const liveAppendResult = liveBarBufferRef.current.append(frame.bars);
    const liveMutation = applyChartCommandsMutable(
      liveChartModelRef.current,
      frame.timeline
    );
    const firstVisibleSequence = liveBarBufferRef.current.first?.sequence ?? 0;
    const activeWindowBucket = Math.floor(
      firstVisibleSequence / ACTIVE_WINDOW_MAINTENANCE_INTERVAL
    );
    const maintainActiveWindow =
      liveAppendResult.windowShifted &&
      activeWindowBucket !== activeWindowBucketRef.current;
    if (maintainActiveWindow) activeWindowBucketRef.current = activeWindowBucket;
    const pruneSummary = maintainActiveWindow
      ? pruneLiveChartState()
      : { pointsRemoved: 0, drawingsRemoved: 0 };

    if (browsingHistoryRef.current) return;

    const appendResult = barBufferRef.current.append(frame.bars);
    chartModelRef.current = liveChartModelRef.current;

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

      if (
        liveMutation.seriesChanged ||
        liveMutation.seriesPoints > 0 ||
        pruneSummary.pointsRemoved > 0
      ) {
        currentAdapter.setStrategyState(
          indicatorsVisibleRef.current
            ? chartModelRef.current
            : withoutIndicatorSeries(chartModelRef.current),
          tickSize
        );
      }
    });

    const brokerWindowShifted = maintainActiveWindow;
    if (brokerWindowShifted) refreshBrokerDrawings();

    if (
      liveMutation.drawingsChanged ||
      pruneSummary.drawingsRemoved > 0 ||
      brokerWindowShifted
    ) {
      rebuildDrawingIndex();
      overlayRef.current?.invalidate();
    }
    scheduleHudRefresh();
  }, [
    pruneLiveChartState,
    rebuildDrawingIndex,
    refreshBrokerDrawings,
    runChartOperation,
    scheduleHudRefresh,
    tickSize
  ]);

  const applyResetFrame = useCallback((frame: ReplayFrame) => {
    liveBarBufferRef.current.replace(frame.bars);
    applyChartCommandsMutable(liveChartModelRef.current, frame.timeline);
    pruneLiveChartState();
    if (browsingHistoryRef.current) return;
    barBufferRef.current.replace(frame.bars);
    chartModelRef.current = liveChartModelRef.current;
    appendedSinceCompactionRef.current = 0;
    activeWindowBucketRef.current = liveBarBufferRef.current.first
      ? Math.floor(liveBarBufferRef.current.first.sequence / ACTIVE_WINDOW_MAINTENANCE_INTERVAL)
      : null;
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
  }, [pruneLiveChartState, refreshBrokerDrawings, runChartOperation, scheduleHudRefresh, tickSize]);

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

    const unsubscribe = nextAdapter.subscribeRender(reason => {
      renderCounterRef.current += 1;
      if (reason === "viewport") viewportHandlerRef.current();
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
    historyAbortRef.current?.abort();
    historyAbortRef.current = null;
    historyRequestKeyRef.current = "";
    historyLoadingRef.current = false;
    historyStartReachedRef.current = false;
    browsingHistoryRef.current = false;
    setHistoryMode(false);
    setHistoryLoading(false);
    liveBarBufferRef.current.replace(bars);
    barBufferRef.current.replace(bars);
    liveChartModelRef.current = cloneChartState(chartState);
    pruneChartStateForBuffer(liveChartModelRef.current, liveBarBufferRef.current);
    chartModelRef.current = liveChartModelRef.current;
    appendedSinceCompactionRef.current = 0;
    activeWindowBucketRef.current = liveBarBufferRef.current.first
      ? Math.floor(liveBarBufferRef.current.first.sequence / ACTIVE_WINDOW_MAINTENANCE_INTERVAL)
      : null;
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
    if (browsingHistoryRef.current) return;
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
    if (normalized.followLatest && browsingHistoryRef.current) {
      restoreLatestWindow();
      return;
    }
    applyCurrentViewport();
  }, [symbol, timeframe, viewport, applyCurrentViewport, restoreLatestWindow]);

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
    if (historyFetchTimerRef.current !== null) window.clearTimeout(historyFetchTimerRef.current);
    historyAbortRef.current?.abort();
    historyLoadingRef.current = false;
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
    if (patch.followLatest === true && browsingHistoryRef.current) {
      restoreLatestWindow();
    }
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

      {historyMode ? (
        <div className="chart-history-window-status">
          <span>{historyLoading ? "Loading older candles…" : "Historical window"}</span>
          <button onClick={() => updateViewport({ followLatest: true })}>Return to latest</button>
        </div>
      ) : null}

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
          <div><span>Window</span><strong>{historyMode ? "history" : "live"}</strong></div>
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

function closedTradeSignature(
  trades: TradeRecord[],
  symbol: string,
  windowKey = ""
): string {
  const recent: string[] = [];
  for (let index = trades.length - 1; index >= 0 && recent.length < 3; index -= 1) {
    const trade = trades[index];
    if (!trade || trade.symbol !== symbol) continue;
    recent.push(`${trade.trade_id}:${trade.exit_time_ns}:${trade.net_pnl}:${trade.exit_reason}`);
  }
  return `${symbol}:${windowKey}:${trades.length}:${recent.join("|")}`;
}

function filterTradesForWindow(
  trades: TradeRecord[],
  symbol: string,
  fromTimeNs: number | null,
  toTimeNs: number | null
): TradeRecord[] {
  if (fromTimeNs === null || toTimeNs === null) {
    return trades.filter(trade => trade.symbol === symbol).slice(-MAX_VISIBLE_DRAWINGS);
  }
  const span = Math.max(1, toTimeNs - fromTimeNs);
  const margin = span * 0.15;
  const from = fromTimeNs - margin;
  const to = toTimeNs + margin;
  return trades.filter(
    trade =>
      trade.symbol === symbol &&
      trade.exit_time_ns >= from &&
      trade.entry_time_ns <= to
  );
}

function pruneChartStateForBuffer(
  state: MaterializedChartState,
  buffer: ReplayBarBuffer
) {
  const first = buffer.first;
  const last = buffer.last;
  if (!first || !last) return { pointsRemoved: 0, drawingsRemoved: 0 };
  const span = Math.max(1, last.close_time_ns - first.open_time_ns);
  return pruneChartStateToWindow(
    state,
    first.open_time_ns,
    last.close_time_ns,
    span * 0.15,
    false
  );
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
