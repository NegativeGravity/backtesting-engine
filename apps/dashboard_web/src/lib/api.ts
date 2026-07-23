import { uiFrameIntervalMs, initialFrameSchedulerStats, type FrameSchedulerStats, type RenderProfile } from "./frameScheduler";
import { mergeAdvanceFramesFast } from "./replayWorkerCore";
import type { ReplayWorkerCommand, ReplayWorkerEvent, ReplayWorkerStatus } from "./replaySocketProtocol";
import type {
  AnalyticsComparisonReport,
  AnalyticsReport,
  ReplayCatalog,
  ReplayControlCommand,
  ReplayFrame,
  SocketMessage,
  Timeframe
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function fetchCatalog(): Promise<ReplayCatalog> {
  const response = await fetch("/api/catalog");
  if (!response.ok) throw new ApiError(`Catalog request failed: ${response.status}`, response.status);
  return response.json() as Promise<ReplayCatalog>;
}

export async function fetchAnalytics(runId: string, endTimeNs?: number): Promise<AnalyticsReport> {
  const url = new URL(`/api/runs/${runId}/analytics`, window.location.origin);
  if (endTimeNs !== undefined) url.searchParams.set("end_time_ns", String(endTimeNs));
  const response = await fetch(url);
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new ApiError(payload?.detail ?? `Analytics request failed: ${response.status}`, response.status);
  }
  return response.json() as Promise<AnalyticsReport>;
}

export async function fetchAnalyticsComparison(runIds: string[]): Promise<AnalyticsComparisonReport> {
  const url = new URL("/api/analytics/compare", window.location.origin);
  for (const runId of runIds) url.searchParams.append("run_id", runId);
  const response = await fetch(url);
  if (!response.ok) throw new ApiError(`Analytics comparison request failed: ${response.status}`, response.status);
  return response.json() as Promise<AnalyticsComparisonReport>;
}

interface ReplayConnection {
  url: string;
  onMessage: (message: SocketMessage) => void;
  onStatus: (status: ReplayWorkerStatus) => void;
  onRenderMessage: (message: SocketMessage) => void;
}

export class ReplaySocket {
  private worker: Worker | null = null;
  private workerRestartTimer: number | null = null;
  private workerRestartAttempts = 0;
  private uiTimer: number | null = null;
  private pendingUiFrame: ReplayFrame | null = null;
  private renderProfile: RenderProfile = "smooth";
  private stats = initialFrameSchedulerStats("worker");
  private statsHandler: ((stats: FrameSchedulerStats) => void) | null = null;
  private visibilityHandler: (() => void) | null = null;
  private connection: ReplayConnection | null = null;

  connect(
    runId: string,
    symbol: string,
    timeframe: Timeframe,
    onMessage: (message: SocketMessage) => void,
    onStatus: (status: ReplayWorkerStatus) => void,
    onRenderMessage: (message: SocketMessage) => void
  ): void {
    this.close();

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = new URL(`${protocol}//${window.location.host}/api/replay/${runId}/ws`);
    url.searchParams.set("symbol", symbol);
    url.searchParams.set("timeframe", timeframe);

    this.connection = {
      url: url.toString(),
      onMessage,
      onStatus,
      onRenderMessage
    };
    this.visibilityHandler = () => this.configureWorker();
    document.addEventListener("visibilitychange", this.visibilityHandler, { passive: true });
    this.startWorker();
  }

  send(command: ReplayControlCommand): void {
    this.post({ type: "send", command });
  }

  setRenderProfile(profile: RenderProfile): void {
    this.renderProfile = profile;
    this.configureWorker();
  }

  subscribeStats(handler: (stats: FrameSchedulerStats) => void): () => void {
    this.statsHandler = handler;
    handler({ ...this.stats });
    return () => {
      if (this.statsHandler === handler) this.statsHandler = null;
    };
  }

  close(): void {
    this.flushUiFrame();
    if (this.uiTimer !== null) window.clearTimeout(this.uiTimer);
    if (this.workerRestartTimer !== null) window.clearTimeout(this.workerRestartTimer);
    this.uiTimer = null;
    this.workerRestartTimer = null;
    this.workerRestartAttempts = 0;
    this.pendingUiFrame = null;
    if (this.visibilityHandler) {
      document.removeEventListener("visibilitychange", this.visibilityHandler);
      this.visibilityHandler = null;
    }
    this.connection = null;
    this.stopWorker();
    this.stats = initialFrameSchedulerStats("worker");
    this.statsHandler?.({ ...this.stats });
  }

  private startWorker(): void {
    const connection = this.connection;
    if (!connection) return;

    this.stopWorker();
    connection.onStatus("connecting");

    let worker: Worker;
    try {
      worker = new Worker(
        new URL("../workers/replaySocket.worker.ts", import.meta.url),
        { type: "module", name: "vex-replay-socket" }
      );
    } catch (error) {
      console.error("Replay worker could not be created", error);
      connection.onStatus("error");
      this.scheduleWorkerRestart();
      return;
    }

    this.worker = worker;
    worker.onmessage = event => {
      if (this.worker !== worker) return;
      this.handleWorkerEvent(event.data as ReplayWorkerEvent);
    };
    worker.onerror = event => {
      if (this.worker !== worker) return;
      console.error("Replay worker crashed", event.message);
      this.worker = null;
      worker.terminate();
      connection.onStatus("error");
      this.scheduleWorkerRestart();
    };
    worker.onmessageerror = () => {
      if (this.worker !== worker) return;
      console.error("Replay worker message decoding failed");
      this.worker = null;
      worker.terminate();
      connection.onStatus("error");
      this.scheduleWorkerRestart();
    };

    worker.postMessage({
      type: "connect",
      url: connection.url,
      profile: this.renderProfile,
      hidden: document.hidden
    } satisfies ReplayWorkerCommand);
  }

  private scheduleWorkerRestart(): void {
    const connection = this.connection;
    if (!connection || this.workerRestartTimer !== null) return;

    this.workerRestartAttempts += 1;
    if (this.workerRestartAttempts > 8) {
      connection.onMessage({
        type: "error",
        detail: "Replay rendering worker could not be restarted. Reload the dashboard to reconnect."
      });
      return;
    }

    const delay = Math.min(10_000, 500 * 2 ** Math.min(5, this.workerRestartAttempts - 1));
    this.workerRestartTimer = window.setTimeout(() => {
      this.workerRestartTimer = null;
      this.startWorker();
    }, delay);
  }

  private stopWorker(): void {
    if (!this.worker) return;
    this.worker.postMessage({ type: "close" } satisfies ReplayWorkerCommand);
    this.worker.terminate();
    this.worker = null;
  }

  private handleWorkerEvent(event: ReplayWorkerEvent): void {
    const connection = this.connection;
    if (!connection) return;

    if (event.type === "status") {
      if (event.status === "connected") this.workerRestartAttempts = 0;
      connection.onStatus(event.status);
      return;
    }
    if (event.type === "stats") {
      this.stats = event.stats;
      this.statsHandler?.({ ...event.stats });
      return;
    }
    if (event.type === "fatal") {
      connection.onStatus("error");
      connection.onMessage({ type: "error", detail: event.detail });
      return;
    }

    const message = event.message;
    try {
      connection.onRenderMessage(message);
    } finally {
      this.post({ type: "ack" });
    }

    if (message.type === "frame" && message.data.frame_type === "advance") {
      const uiFrame: ReplayFrame = { ...message.data, bars: [] };
      this.pendingUiFrame = this.pendingUiFrame
        ? mergeAdvanceFramesFast(this.pendingUiFrame, uiFrame, {
            maxBars: 1,
            maxTimelineItems: 1_000
          })
        : uiFrame;
      this.scheduleUiFrame();
      return;
    }

    this.flushUiFrame();
    connection.onMessage(message);
  }

  private scheduleUiFrame(): void {
    if (this.uiTimer !== null) return;
    this.uiTimer = window.setTimeout(() => {
      this.uiTimer = null;
      this.flushUiFrame();
    }, uiFrameIntervalMs(this.renderProfile));
  }

  private flushUiFrame(): void {
    if (!this.pendingUiFrame) return;
    const frame = this.pendingUiFrame;
    this.pendingUiFrame = null;
    this.connection?.onMessage({ type: "frame", data: frame });
  }

  private configureWorker(): void {
    this.post({
      type: "configure",
      profile: this.renderProfile,
      hidden: document.hidden
    });
  }

  private post(command: ReplayWorkerCommand): void {
    this.worker?.postMessage(command);
  }
}

export async function fetchEngineCatalog(): Promise<import("./types").EngineCatalog> {
  const response = await fetch("/api/engine/catalog");
  if (!response.ok) throw new ApiError(`Engine catalog request failed: ${response.status}`, response.status);
  return response.json() as Promise<import("./types").EngineCatalog>;
}

export async function refreshStrategyPackages(): Promise<import("./types").EngineCatalog> {
  const response = await fetch("/api/engine/strategies/refresh", { method: "POST" });
  if (!response.ok) throw new ApiError(`Strategy refresh failed: ${response.status}`, response.status);
  return response.json() as Promise<import("./types").EngineCatalog>;
}

export async function createLiveRun(
  request: import("./types").LiveRunCreateRequest
): Promise<import("./types").LiveRunState> {
  const response = await fetch("/api/engine/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request)
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new ApiError(payload?.detail ?? `Live run creation failed: ${response.status}`, response.status);
  }
  return response.json() as Promise<import("./types").LiveRunState>;
}
