import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState
} from "react";
import { AlertTriangle, LoaderCircle, PanelBottomOpen } from "lucide-react";
import { AnalyticsDashboard } from "./components/AnalyticsDashboard";
import { BottomDock } from "./components/BottomDock";
import { InspectorPanel } from "./components/InspectorPanel";
import { LiveBacktestLauncher } from "./components/LiveBacktestLauncher";
import { MetricsStrip } from "./components/MetricsStrip";
import { ReplayToolbar } from "./components/ReplayToolbar";
import { ResizeHandle } from "./components/ResizeHandle";
import { TopBar } from "./components/TopBar";
import { TradingChart } from "./components/TradingChart";
import { ApiError, fetchAnalytics, fetchCatalog, ReplaySocket } from "./lib/api";
import { initialFrameSchedulerStats, type FrameSchedulerStats } from "./lib/frameScheduler";
import { ReplayRenderStream } from "./lib/replayRenderStream";
import type { AnalyticsReport, SocketMessage, Timeframe } from "./lib/types";
import { useDashboardPreferences } from "./state/dashboardPreferences";
import { initialReplayState, replayReducer } from "./state/replayState";

const HOTKEY_TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "H1", "H4", "D1"];

export default function App() {
  const [state, dispatch] = useReducer(replayReducer, initialReplayState);
  const socketRef = useRef(new ReplaySocket());
  const renderStreamRef = useRef(new ReplayRenderStream());
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(10);
  const [chartFocused, setChartFocused] = useState(false);
  const [mode, setMode] = useState<"replay" | "analytics" | "live">("replay");
  const [analyticsScope, setAnalyticsScope] = useState<"full" | "cursor">("full");
  const [fullAnalytics, setFullAnalytics] = useState<AnalyticsReport | null>(null);
  const [cursorAnalytics, setCursorAnalytics] = useState<AnalyticsReport | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsUnavailable, setAnalyticsUnavailable] = useState(false);
  const [frameStats, setFrameStats] = useState<FrameSchedulerStats>(initialFrameSchedulerStats);
  const [preferences, updatePreferences, applyLayoutPreset] = useDashboardPreferences();

  useEffect(() => {
    fetchCatalog()
      .then(catalog => dispatch({ type: "catalog_loaded", catalog }))
      .catch(error => dispatch({ type: "error", error: String(error) }));
  }, []);

  const selectedRun = useMemo(
    () => state.catalog?.runs.find(run => run.run_id === state.selectedRunId) ?? null,
    [state.catalog, state.selectedRunId]
  );

  useEffect(() => {
    socketRef.current.setRenderProfile(preferences.renderProfile);
  }, [preferences.renderProfile]);

  useEffect(() => {
    if (!preferences.diagnosticsVisible) {
      setFrameStats(initialFrameSchedulerStats());
      return;
    }
    return socketRef.current.subscribeStats(setFrameStats);
  }, [preferences.diagnosticsVisible]);

  useEffect(() => {
    if (!selectedRun) return;
    const socket = socketRef.current;
    socket.connect(
      selectedRun.run_id,
      selectedRun.default_symbol,
      selectedRun.default_timeframe,
      message => handleSocketMessage(message, dispatch, setPlaying, setSpeed),
      connection => dispatch({ type: "connection_changed", connection }),
      message => renderStreamRef.current.publish(message)
    );
    return () => socket.close();
  }, [selectedRun]);

  useEffect(() => {
    if (!selectedRun) return;
    let cancelled = false;
    setAnalyticsLoading(true);
    setAnalyticsUnavailable(false);
    setFullAnalytics(null);
    setCursorAnalytics(null);
    fetchAnalytics(selectedRun.run_id)
      .then(report => {
        if (!cancelled) setFullAnalytics(report);
      })
      .catch(error => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 409) {
          setAnalyticsUnavailable(true);
          return;
        }
        dispatch({ type: "error", error: String(error) });
      })
      .finally(() => {
        if (!cancelled) setAnalyticsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRun]);

  useEffect(() => {
    if (mode !== "analytics" || analyticsScope !== "cursor" || !selectedRun || !state.bootstrap || playing) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setAnalyticsLoading(true);
      fetchAnalytics(selectedRun.run_id, state.bootstrap?.cursor_time_ns)
        .then(report => {
          if (!cancelled) setCursorAnalytics(report);
        })
        .catch(error => {
          if (cancelled) return;
          if (error instanceof ApiError && error.status === 409) {
            setAnalyticsUnavailable(true);
            return;
          }
          dispatch({ type: "error", error: String(error) });
        })
        .finally(() => {
          if (!cancelled) setAnalyticsLoading(false);
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [mode, analyticsScope, selectedRun, state.bootstrap?.cursor_time_ns, playing]);

  const send = useCallback((action: Parameters<ReplaySocket["send"]>[0]) => {
    socketRef.current.send(action);
  }, []);

  const changeRun = useCallback((runId: string) => {
    setPlaying(false);
    setAnalyticsScope("full");
    dispatch({ type: "run_selected", runId });
  }, []);

  const changeTimeframe = useCallback((timeframe: Timeframe) => {
    setPlaying(false);
    send({ action: "set_timeframe", value: timeframe });
  }, [send]);

  const togglePlay = useCallback(() => {
    setPlaying(current => {
      const next = !current;
      send({ action: next ? "play" : "pause" });
      return next;
    });
  }, [send]);

  const stepBack = useCallback(() => {
    setPlaying(false);
    send({ action: "step_backward" });
  }, [send]);

  const stepForward = useCallback(() => {
    setPlaying(false);
    send({ action: "step_forward", value: 1 });
  }, [send]);

  const reset = useCallback(() => {
    setPlaying(false);
    send({ action: "reset" });
  }, [send]);

  const changeSpeed = useCallback((value: number) => {
    setSpeed(value);
    send({ action: "set_speed", value });
  }, [send]);

  const seek = useCallback((value: number) => {
    setPlaying(false);
    send({ action: "seek_progress", value });
  }, [send]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      if (mode !== "replay") return;
      if (event.code === "Space") {
        event.preventDefault();
        togglePlay();
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        stepBack();
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        stepForward();
        return;
      }
      if (event.key.toLowerCase() === "r") {
        reset();
        return;
      }
      if (event.key.toLowerCase() === "f") {
        setChartFocused(value => !value);
        return;
      }
      if (event.key.toLowerCase() === "i") {
        dispatch({ type: "inspector_toggled" });
        return;
      }
      if (event.key.toLowerCase() === "d") {
        updatePreferences({ dockCollapsed: !preferences.dockCollapsed });
        return;
      }
      if (event.key.toLowerCase() === "m") {
        updatePreferences({ metricsVisible: !preferences.metricsVisible });
        return;
      }
      const number = Number(event.key);
      if (number >= 1 && number <= HOTKEY_TIMEFRAMES.length) {
        const timeframe = HOTKEY_TIMEFRAMES[number - 1];
        if (timeframe && selectedRun?.available_timeframes.includes(timeframe)) changeTimeframe(timeframe);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mode, togglePlay, stepBack, stepForward, reset, changeTimeframe, selectedRun, preferences.dockCollapsed, preferences.metricsVisible, updatePreferences]);

  if (state.error) {
    return (
      <main className="full-page-message error-message">
        <AlertTriangle size={34} />
        <strong>VEX dashboard failed to initialize</strong>
        <span>{state.error}</span>
      </main>
    );
  }

  if (state.catalog && state.catalog.runs.length === 0) {
    return (
      <div className="app-shell live-shell">
        <header className="empty-catalog-header">
          <strong>VEX Backtesting Platform</strong>
          <span>The engine is online. Add or select a strategy package to create the first run.</span>
        </header>
        <LiveBacktestLauncher onRunCreated={async runId => {
          try {
            const catalog = await fetchCatalog();
            dispatch({ type: "catalog_loaded", catalog });
            dispatch({ type: "run_selected", runId });
            setMode("replay");
          } catch (error) {
            dispatch({ type: "error", error: String(error) });
          }
        }} />
      </div>
    );
  }

  if (!state.catalog || !state.selectedRunId || !selectedRun || !state.bootstrap || !state.account) {
    return (
      <main className="full-page-message">
        <LoaderCircle size={34} className="spin" />
        <strong>Loading VEX workstation</strong>
        <span>Connecting to replay, broker state and analytics services</span>
      </main>
    );
  }

  const bootstrap = state.bootstrap;
  const tickSize = Number(bootstrap.price_tick_size);
  const activeAnalytics = analyticsScope === "cursor" ? cursorAnalytics ?? fullAnalytics : fullAnalytics;
  const inspectorVisible = !chartFocused && state.inspectorOpen;
  const dockVisible = !chartFocused && !preferences.dockCollapsed;
  const metricsVisible = !chartFocused && preferences.metricsVisible;

  const shellStyle = {
    "--inspector-width": `${preferences.inspectorWidth}px`,
    "--dock-height": `${preferences.dockHeight}px`
  } as React.CSSProperties;

  const topBar = (
    <TopBar
      catalog={state.catalog}
      selectedRunId={state.selectedRunId}
      symbol={bootstrap.symbol}
      timeframe={bootstrap.timeframe}
      connection={state.connection}
      inspectorOpen={state.inspectorOpen}
      dockCollapsed={preferences.dockCollapsed}
      metricsVisible={preferences.metricsVisible}
      diagnosticsVisible={preferences.diagnosticsVisible}
      renderProfile={preferences.renderProfile}
      mode={mode}
      onRunChange={changeRun}
      onTimeframeChange={changeTimeframe}
      onInspectorToggle={() => dispatch({ type: "inspector_toggled" })}
      onDockToggle={() => updatePreferences({ dockCollapsed: !preferences.dockCollapsed })}
      onMetricsToggle={() => updatePreferences({ metricsVisible: !preferences.metricsVisible })}
      onDiagnosticsToggle={() => updatePreferences({ diagnosticsVisible: !preferences.diagnosticsVisible })}
      onRenderProfileChange={renderProfile => updatePreferences({ renderProfile })}
      onLayoutPreset={applyLayoutPreset}
      onModeChange={next => {
        setMode(next);
        if (next === "analytics") setPlaying(false);
      }}
    />
  );

  if (mode === "live") {
    return (
      <div className="app-shell live-shell" style={shellStyle}>
        {topBar}
        <LiveBacktestLauncher onRunCreated={async runId => {
          try {
            const catalog = await fetchCatalog();
            dispatch({ type: "catalog_loaded", catalog });
            dispatch({ type: "run_selected", runId });
            setMode("replay");
          } catch (error) {
            dispatch({ type: "error", error: String(error) });
          }
        }} />
      </div>
    );
  }

  if (mode === "analytics") {
    return (
      <div className="app-shell analytics-shell" style={shellStyle}>
        {topBar}
        {activeAnalytics ? (
          <AnalyticsDashboard report={activeAnalytics} scope={analyticsScope} loading={analyticsLoading} onScopeChange={setAnalyticsScope} />
        ) : analyticsUnavailable ? (
          <main className="full-page-message analytics-page-loader">
            <strong>Analytics will be available after the live run is finalized</strong>
            <span>Continue candle-by-candle replay or press Play to complete the backtest.</span>
          </main>
        ) : (
          <main className="full-page-message analytics-page-loader"><LoaderCircle size={30} className="spin" /><strong>Building analytics view</strong></main>
        )}
        <footer className="status-bar analytics-status">
          <span>Run: {bootstrap.run.run_id}</span>
          <span>Report: {activeAnalytics?.report_id ?? "loading"}</span>
          <span>Scope: {analyticsScope}</span>
          <span className="status-right">Exact execution-bar equity · UTC aggregation</span>
        </footer>
      </div>
    );
  }

  return (
    <div
      className={`app-shell replay-shell ${inspectorVisible ? "with-inspector" : ""} ${chartFocused ? "chart-focus" : ""} ${metricsVisible ? "with-metrics" : "without-metrics"} ${dockVisible ? "with-dock" : "without-dock"} ${preferences.compactMode ? "compact-mode" : ""}`}
      style={shellStyle}
    >
      {topBar}
      {metricsVisible ? <MetricsStrip metrics={bootstrap.run.metrics} account={state.account} /> : null}
      <ReplayToolbar
        playing={playing}
        speed={speed}
        progress={Number(bootstrap.progress)}
        cursorTimeNs={bootstrap.cursor_time_ns}
        onPlayPause={togglePlay}
        onStepBack={stepBack}
        onStepForward={stepForward}
        onReset={reset}
        onSpeedChange={changeSpeed}
        onSeek={seek}
      />

      <div className="workspace">
        <main className="chart-workspace">
          <TradingChart
            bars={bootstrap.bars}
            chartState={state.chartState}
            tickSize={tickSize}
            symbol={bootstrap.symbol}
            timeframe={bootstrap.timeframe}
            focused={chartFocused}
            diagnosticsVisible={preferences.diagnosticsVisible}
            frameStats={frameStats}
            renderStream={renderStreamRef.current}
            trades={state.trades}
            positions={state.positions}
            onFocusToggle={() => setChartFocused(value => !value)}
          />
        </main>
        {inspectorVisible ? (
          <>
            <ResizeHandle
              axis="x"
              value={preferences.inspectorWidth}
              minimum={240}
              maximum={520}
              direction={-1}
              onChange={value => updatePreferences({ inspectorWidth: value })}
              label="Resize inspector"
            />
            <InspectorPanel
              account={state.account}
              timeline={state.timeline}
              positions={state.positions}
              orders={state.orders}
              tickSize={tickSize}
            />
          </>
        ) : null}
      </div>

      {dockVisible ? (
        <>
          <ResizeHandle
            axis="y"
            value={preferences.dockHeight}
            minimum={120}
            maximum={520}
            direction={-1}
            onChange={value => updatePreferences({ dockHeight: value })}
            label="Resize bottom dock"
          />
          <BottomDock
            activeTab={state.activeBottomTab}
            onTabChange={tab => dispatch({ type: "bottom_tab_changed", tab })}
            trades={state.trades}
            orders={state.orders}
            timeline={state.timeline}
            metrics={bootstrap.run.metrics}
            account={state.account}
            tickSize={tickSize}
          />
        </>
      ) : !chartFocused ? (
        <button className="dock-restore" onClick={() => updatePreferences({ dockCollapsed: false })}>
          <PanelBottomOpen size={14} /> Open activity dock
        </button>
      ) : null}

      <footer className="status-bar">
        <span>Run: {bootstrap.run.run_id}</span>
        <span>Strategy: {bootstrap.run.strategy_id}</span>
        <span>Cursor: {bootstrap.cursor_sequence.toLocaleString()}</span>
        <span>Chart feed: dedicated worker</span>
        <span>Events: {state.timeline.length.toLocaleString()}</span>
        <span className="shortcut-hint">Space play · ←/→ candle · 1–6 timeframe · F focus</span>
        <span className="status-right">Deterministic OHLC replay · {preferences.renderProfile} rendering</span>
      </footer>
    </div>
  );
}

function handleSocketMessage(
  message: SocketMessage,
  dispatch: React.Dispatch<Parameters<typeof replayReducer>[1]>,
  setPlaying: React.Dispatch<React.SetStateAction<boolean>>,
  setSpeed: React.Dispatch<React.SetStateAction<number>>
): void {
  if (message.type === "bootstrap") {
    setPlaying(false);
    dispatch({ type: "bootstrap_received", bootstrap: message.data });
    return;
  }
  if (message.type === "frame") {
    setPlaying(message.data.playing);
    setSpeed(Number(message.data.speed));
    dispatch({ type: "frame_received", frame: message.data });
    return;
  }
  dispatch({ type: "error", error: message.detail });
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(target.tagName);
}
