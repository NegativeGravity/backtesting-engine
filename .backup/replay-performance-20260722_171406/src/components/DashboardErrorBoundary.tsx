import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCcw, RotateCcw } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  incidentId: string | null;
}

const DIAGNOSTIC_KEY = "vex.dashboard.last-crash";

export class DashboardErrorBoundary extends Component<Props, State> {
  state: State = { error: null, incidentId: null };

  static getDerivedStateFromError(error: Error): State {
    return {
      error,
      incidentId: createIncidentId()
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    const payload = {
      incidentId: this.state.incidentId,
      capturedAt: new Date().toISOString(),
      message: error.message,
      stack: error.stack ?? null,
      componentStack: info.componentStack ?? null,
      userAgent: navigator.userAgent,
      location: window.location.href
    };
    try {
      window.sessionStorage.setItem(DIAGNOSTIC_KEY, JSON.stringify(payload));
    } catch {
      console.warn("VEX dashboard crash diagnostics could not be persisted");
    }
    console.error("VEX dashboard render failure", payload);
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;

    return (
      <main className="dashboard-crash-screen" role="alert">
        <div className="dashboard-crash-card">
          <div className="dashboard-crash-icon"><AlertTriangle size={28} /></div>
          <div>
            <span className="dashboard-crash-kicker">Dashboard recovered from a render failure</span>
            <h1>The backtest engine is still running</h1>
            <p>
              Only the browser view failed. Reloading reconnects to the replay service without
              stopping the engine process.
            </p>
          </div>
          <pre>{this.state.error.message}</pre>
          <div className="dashboard-crash-actions">
            <button onClick={() => window.location.reload()}>
              <RefreshCcw size={15} /> Reload dashboard
            </button>
            <button className="secondary" onClick={resetDashboardStorage}>
              <RotateCcw size={15} /> Reset dashboard settings
            </button>
          </div>
          <small>Incident: {this.state.incidentId}</small>
        </div>
      </main>
    );
  }
}

function createIncidentId(): string {
  return `vex-ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function resetDashboardStorage(): void {
  try {
    const keys: string[] = [];
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (key?.startsWith("vex.")) keys.push(key);
    }
    for (const key of keys) window.localStorage.removeItem(key);
  } finally {
    window.location.reload();
  }
}
