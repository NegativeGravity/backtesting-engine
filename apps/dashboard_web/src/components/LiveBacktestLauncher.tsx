import { useEffect, useMemo, useState } from "react";
import { LoaderCircle, Play, RefreshCw } from "lucide-react";
import { createLiveRun, fetchEngineCatalog, refreshStrategyPackages } from "../lib/api";
import type { EngineCatalog } from "../lib/types";

interface Props {
  onRunCreated: (runId: string) => void;
}

export function LiveBacktestLauncher({ onRunCreated }: Props) {
  const [catalog, setCatalog] = useState<EngineCatalog | null>(null);
  const [strategyId, setStrategyId] = useState("");
  const [runUntilEnd, setRunUntilEnd] = useState(true);
  const [maxBatches, setMaxBatches] = useState(5000);
  const [speed, setSpeed] = useState(10);
  const [startPaused, setStartPaused] = useState(true);
  const [visualizationMode, setVisualizationMode] = useState<"auto" | "replay" | "turbo">("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await fetchEngineCatalog();
      setCatalog(next);
      setStrategyId(current => current || next.strategies[0]?.package_id || "");
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const selected = useMemo(
    () => catalog?.strategies.find(item => item.package_id === strategyId) ?? null,
    [catalog, strategyId]
  );

  const refresh = async () => {
    setBusy(true);
    setError(null);
    try {
      setCatalog(await refreshStrategyPackages());
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!strategyId) return;
    setBusy(true);
    setError(null);
    try {
      const run = await createLiveRun({
        strategy_package_id: strategyId,
        start_paused: startPaused,
        speed_bars_per_second: speed,
        visualization_mode: visualizationMode,
        ui_snapshot_interval_ms: visualizationMode === "replay" ? 100 : 500,
        ui_window_bars: 2400,
        ui_timeline_limit: 2000,
        ...(runUntilEnd ? {} : { max_close_batches: maxBatches })
      });
      onRunCreated(run.run_id);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="live-launcher">
      <section className="live-launch-card">
        <div className="live-launch-heading">
          <div>
            <span>Long-running engine</span>
            <h1>Candle-by-candle strategy backtest</h1>
            <p>The engine stays online. Strategy packages are discovered from the mounted strategies directory and each closed candle is processed deterministically while the dashboard receives a bounded, coalesced visualization stream.</p>
          </div>
          <button className="secondary-action" onClick={() => void refresh()} disabled={busy}><RefreshCw size={15} /> Refresh strategies</button>
        </div>
        <div className="live-form-grid">
          <label className="live-field"><span>Strategy package</span><select value={strategyId} onChange={event => setStrategyId(event.target.value)}>{catalog?.strategies.map(item => <option key={item.package_id} value={item.package_id}>{item.name} · {item.version}</option>)}</select></label>
          <label className="live-check"><input type="checkbox" checked={runUntilEnd} onChange={event => setRunUntilEnd(event.target.checked)} /><span>Run until end of available data</span></label>
          <label className="live-field"><span>Maximum close batches</span><input type="number" min="1" value={maxBatches} disabled={runUntilEnd} onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value)) setMaxBatches(Math.max(1, Math.trunc(value))); }} /></label>
          <label className="live-field"><span>Bars per second</span><input type="number" min="1" max="1000000" value={speed} onChange={event => setSpeed(Math.min(1000000, Math.max(1, Number(event.target.value))))} /></label>
          <label className="live-field"><span>Dashboard stream</span><select value={visualizationMode} onChange={event => setVisualizationMode(event.target.value as "auto" | "replay" | "turbo")}><option value="auto">Auto · Turbo for high speed</option><option value="turbo">Turbo · million-candle mode</option><option value="replay">Replay · every visible update</option></select></label>
          <label className="live-check"><input type="checkbox" checked={startPaused} onChange={event => setStartPaused(event.target.checked)} /><span>Start paused for manual candle stepping</span></label>
        </div>
        {selected ? <div className="strategy-summary"><strong>{selected.name}</strong><span>{selected.description}</span><code>{selected.entrypoint}</code></div> : null}
        {error ? <div className="live-error">{error}</div> : null}
        <button className="primary-action" onClick={() => void start()} disabled={busy || !strategyId}>{busy ? <LoaderCircle className="spin" size={16} /> : <Play size={16} fill="currentColor" />} Create live backtest</button>
      </section>
      <section className="live-runs-card">
        <h2>Active engine runs</h2>
        <div className="live-run-list">
          {catalog?.runs.length ? catalog.runs.map(run => <button key={run.run_id} onClick={() => onRunCreated(run.run_id)}><strong>{run.descriptor.name}</strong><span>{run.status} · {run.processed_close_batches} batches · {(Number(run.progress) * 100).toFixed(2)}%</span></button>) : <span>No active runs</span>}
        </div>
      </section>
    </main>
  );
}
