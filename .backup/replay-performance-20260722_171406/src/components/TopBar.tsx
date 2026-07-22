import { memo } from "react";
import {
  Activity,
  BarChart3,
  CandlestickChart,
  Gauge,
  LayoutDashboard,
  Maximize2,
  PanelBottomClose,
  PanelBottomOpen,
  PanelRightClose,
  PanelRightOpen,
  PlaySquare,
  Rows3
} from "lucide-react";
import type { RenderProfile } from "../lib/frameScheduler";
import type { ReplayCatalog, Timeframe } from "../lib/types";
import type { LayoutPreset } from "../state/dashboardPreferences";
import type { ConnectionStatus } from "../state/replayState";

interface Props {
  catalog: ReplayCatalog;
  selectedRunId: string;
  symbol: string;
  timeframe: Timeframe;
  connection: ConnectionStatus;
  inspectorOpen: boolean;
  dockCollapsed: boolean;
  metricsVisible: boolean;
  diagnosticsVisible: boolean;
  renderProfile: RenderProfile;
  mode: "replay" | "analytics" | "live";
  onRunChange: (runId: string) => void;
  onTimeframeChange: (timeframe: Timeframe) => void;
  onInspectorToggle: () => void;
  onDockToggle: () => void;
  onMetricsToggle: () => void;
  onDiagnosticsToggle: () => void;
  onRenderProfileChange: (profile: RenderProfile) => void;
  onLayoutPreset: (preset: LayoutPreset) => void;
  onModeChange: (mode: "replay" | "analytics" | "live") => void;
}

const chartTimeframes = [
  ["M1", "1m"],
  ["M5", "5m"],
  ["M15", "15m"],
  ["H1", "1H"],
  ["H4", "4H"],
  ["D1", "1D"]
] as const satisfies readonly (readonly [Timeframe, string])[];

export const TopBar = memo(function TopBar({
  catalog,
  selectedRunId,
  symbol,
  timeframe,
  connection,
  inspectorOpen,
  dockCollapsed,
  metricsVisible,
  diagnosticsVisible,
  renderProfile,
  mode,
  onRunChange,
  onTimeframeChange,
  onInspectorToggle,
  onDockToggle,
  onMetricsToggle,
  onDiagnosticsToggle,
  onRenderProfileChange,
  onLayoutPreset,
  onModeChange
}: Props) {
  const run = catalog.runs.find(item => item.run_id === selectedRunId) ?? catalog.runs[0];
  if (!run) return null;
  return (
    <header className="top-bar">
      <div className="brand">
        <div className="brand-mark"><CandlestickChart size={18} /></div>
        <div className="brand-copy">
          <strong>VEX</strong>
          <span>Backtesting Workstation</span>
        </div>
      </div>

      <div className="workspace-switch" aria-label="Workspace">
        <button className={mode === "replay" ? "active" : ""} onClick={() => onModeChange("replay")}>
          <CandlestickChart size={13} /> Replay
        </button>
        <button className={mode === "analytics" ? "active" : ""} onClick={() => onModeChange("analytics")}>
          <BarChart3 size={13} /> Analytics
        </button>
        <button className={mode === "live" ? "active" : ""} onClick={() => onModeChange("live")}>
          <PlaySquare size={13} /> Launcher
        </button>
      </div>

      <div className="top-controls">
        <label className="field run-field">
          <span>Run</span>
          <select value={selectedRunId} onChange={event => onRunChange(event.target.value)}>
            {catalog.runs.map(item => (
              <option key={item.run_id} value={item.run_id}>{item.name}</option>
            ))}
          </select>
        </label>
        <div className="symbol-chip">
          <strong>{symbol}</strong>
          <span>MT5</span>
        </div>
        <div className="timeframe-switch" aria-label="Chart timeframe">
          {chartTimeframes.map(([value, label]) => {
            const available = run.available_timeframes.includes(value);
            return (
              <button
                key={value}
                type="button"
                className={timeframe === value ? "active" : ""}
                disabled={!available}
                onClick={() => onTimeframeChange(value)}
                title={available ? `Switch to ${label}` : `${label} is unavailable for this run`}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="top-actions">
        <label className="render-profile" title="Controls browser rendering cadence, not backtest determinism">
          <Gauge size={13} />
          <select value={renderProfile} onChange={event => onRenderProfileChange(event.target.value as RenderProfile)}>
            <option value="smooth">Smooth</option>
            <option value="balanced">Balanced</option>
            <option value="throughput">Fast</option>
          </select>
        </label>
        <div className="layout-presets" aria-label="Layout presets">
          <button onClick={() => onLayoutPreset("focus")} title="Chart focus preset"><Maximize2 size={14} /></button>
          <button onClick={() => onLayoutPreset("balanced")} title="Balanced preset"><LayoutDashboard size={14} /></button>
          <button onClick={() => onLayoutPreset("analysis")} title="Analysis preset"><Rows3 size={14} /></button>
        </div>
        <button className={`icon-button ${metricsVisible ? "active" : ""}`} onClick={onMetricsToggle} title="Toggle metrics ribbon">
          <BarChart3 size={16} />
        </button>
        <button className={`icon-button ${dockCollapsed ? "" : "active"}`} onClick={onDockToggle} title="Toggle bottom dock">
          {dockCollapsed ? <PanelBottomOpen size={16} /> : <PanelBottomClose size={16} />}
        </button>
        <button className={`icon-button ${diagnosticsVisible ? "active" : ""}`} onClick={onDiagnosticsToggle} title="Toggle performance diagnostics">
          <Activity size={16} />
        </button>
        {mode !== "analytics" ? (
          <button className={`icon-button ${inspectorOpen ? "active" : ""}`} onClick={onInspectorToggle} aria-label="Toggle inspector">
            {inspectorOpen ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}
          </button>
        ) : null}
        <div className={`connection-status ${connection}`} title={`Engine connection: ${connection}`}>
          <span className="connection-dot" />
          <span>{connection}</span>
        </div>
      </div>
    </header>
  );
});
