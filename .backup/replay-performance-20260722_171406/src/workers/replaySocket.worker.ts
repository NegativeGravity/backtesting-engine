import { frameIntervalMs, initialFrameSchedulerStats, type FrameSchedulerStats, type RenderProfile } from "../lib/frameScheduler";
import { mergeAdvanceFramesFast } from "../lib/replayWorkerCore";
import type { ReplayWorkerCommand, ReplayWorkerEvent } from "../lib/replaySocketProtocol";
import type { ReplayFrame, SocketMessage } from "../lib/types";

interface WorkerScope {
  postMessage(message: ReplayWorkerEvent): void;
  onmessage: ((event: MessageEvent<ReplayWorkerCommand>) => void) | null;
}

const scope = globalThis as unknown as WorkerScope;
const MAX_PENDING_TIMELINE_ITEMS = 20_000;
const MAX_PENDING_BARS = 12_000;

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let flushTimer: ReturnType<typeof setTimeout> | null = null;
let statsTimer: ReturnType<typeof setTimeout> | null = null;
let pendingFrame: ReplayFrame | null = null;
let pendingFrameCount = 0;
let outboundQueue: SocketMessage[] = [];
let inFlight = false;
let closedByUser = true;
let currentUrl = "";
let generation = 0;
let renderProfile: RenderProfile = "smooth";
let hidden = false;
let speed = 10;
let lastFlushAt = performance.now();
let stats: FrameSchedulerStats = initialFrameSchedulerStats("worker");
let resyncInProgress = false;

scope.onmessage = event => {
  const command = event.data;
  if (command.type === "connect") {
    renderProfile = command.profile;
    hidden = command.hidden;
    connect(command.url);
    return;
  }
  if (command.type === "configure") {
    renderProfile = command.profile;
    hidden = command.hidden;
    scheduleFlush();
    return;
  }
  if (command.type === "send") {
    if (command.command.action === "set_speed" && command.command.value !== undefined) {
      speed = Number(command.command.value);
    }
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(command.command));
    }
    return;
  }
  if (command.type === "ack") {
    inFlight = false;
    sendNext();
    return;
  }
  close(true);
};

function connect(url: string): void {
  resetTransport(false, false);
  currentUrl = url;
  generation += 1;
  const localGeneration = generation;
  post({ type: "status", status: "connecting" });

  const nextSocket = new WebSocket(url);
  socket = nextSocket;

  nextSocket.onopen = () => {
    if (localGeneration !== generation) return;
    post({ type: "status", status: "connected" });
  };

  nextSocket.onmessage = event => {
    if (localGeneration !== generation) return;
    try {
      const message = JSON.parse(String(event.data)) as SocketMessage;
      ingest(message);
    } catch (error) {
      post({ type: "fatal", detail: `Replay message parse failed: ${formatError(error)}` });
    }
  };

  nextSocket.onerror = () => {
    if (localGeneration !== generation) return;
    post({ type: "status", status: "error" });
  };

  nextSocket.onclose = () => {
    if (localGeneration !== generation) return;
    socket = null;
    post({ type: "status", status: "disconnected" });
    if (!closedByUser) {
      stats.reconnects += 1;
      emitStatsSoon();
      reconnectTimer = setTimeout(() => connect(currentUrl), 1500);
    }
  };
}

function ingest(message: SocketMessage): void {
  if (message.type === "resync_required") {
    requestResync();
    return;
  }

  if (message.type === "frame" && message.data.frame_type === "advance") {
    speed = Number(message.data.speed);
    stats.receivedFrames += 1;
    pendingFrameCount += 1;
    pendingFrame = pendingFrame
      ? mergeAdvanceFramesFast(pendingFrame, message.data)
      : message.data;
    stats.pendingFrames = pendingFrameCount;

    if (
      pendingFrame.timeline.length >= MAX_PENDING_TIMELINE_ITEMS ||
      pendingFrame.bars.length >= MAX_PENDING_BARS
    ) {
      requestResync();
      return;
    }

    scheduleFlush();
    emitStatsSoon();
    return;
  }

  if (message.type === "bootstrap") {
    pendingFrame = null;
    pendingFrameCount = 0;
    resyncInProgress = false;
    stats.pendingFrames = 0;
    outboundQueue = outboundQueue.filter(item => item.type === "error");
    enqueue(message, true);
    return;
  }

  flushPendingToQueue();
  enqueue(message, message.type === "error");
}

function requestResync(): void {
  if (resyncInProgress || !currentUrl) return;
  resetTransport(false, false);
  resyncInProgress = true;
  stats.pendingFrames = 0;
  stats.resyncs += 1;
  emitStatsSoon();
  post({ type: "status", status: "connecting" });
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    resyncInProgress = false;
    connect(currentUrl);
  }, 100);
}

function scheduleFlush(): void {
  if (!pendingFrame || flushTimer !== null) return;
  if (inFlight || outboundQueue.length > 0) return;
  const interval = frameIntervalMs(renderProfile, speed, hidden);
  const elapsed = performance.now() - lastFlushAt;
  const delay = Math.max(0, interval - elapsed);
  flushTimer = setTimeout(() => {
    flushTimer = null;
    flushPendingToQueue();
    sendNext();
  }, delay);
}

function flushPendingToQueue(): void {
  if (!pendingFrame) return;
  const frame = pendingFrame;
  const batchSize = pendingFrameCount;
  pendingFrame = null;
  pendingFrameCount = 0;
  stats.renderedFrames += 1;
  stats.mergedFrames += Math.max(0, batchSize - 1);
  stats.lastBatchSize = batchSize;
  stats.pendingFrames = 0;
  lastFlushAt = performance.now();
  outboundQueue.push({ type: "frame", data: frame });
  emitStatsSoon();
}

function enqueue(message: SocketMessage, replaceQueue: boolean): void {
  if (replaceQueue) outboundQueue = [];
  if (message.type === "frame" && message.data.frame_type === "state") {
    const last = outboundQueue.at(-1);
    if (last?.type === "frame" && last.data.frame_type === "state") {
      outboundQueue[outboundQueue.length - 1] = message;
    } else {
      outboundQueue.push(message);
    }
  } else {
    outboundQueue.push(message);
  }
  sendNext();
}

function sendNext(): void {
  if (inFlight) return;
  const message = outboundQueue.shift();
  if (message) {
    inFlight = true;
    post({ type: "message", message });
    return;
  }
  scheduleFlush();
}

function emitStatsSoon(): void {
  if (statsTimer !== null) return;
  statsTimer = setTimeout(() => {
    statsTimer = null;
    post({ type: "stats", stats: { ...stats } });
  }, 250);
}

function resetTransport(markClosedByUser: boolean, resetStats: boolean): void {
  closedByUser = markClosedByUser;
  generation += 1;
  if (reconnectTimer !== null) clearTimeout(reconnectTimer);
  if (flushTimer !== null) clearTimeout(flushTimer);
  if (statsTimer !== null) clearTimeout(statsTimer);
  reconnectTimer = null;
  flushTimer = null;
  statsTimer = null;
  pendingFrame = null;
  pendingFrameCount = 0;
  outboundQueue = [];
  inFlight = false;
  resyncInProgress = false;
  const activeSocket = socket;
  socket = null;
  activeSocket?.close();
  if (resetStats) stats = initialFrameSchedulerStats("worker");
}

function close(markClosedByUser: boolean): void {
  resetTransport(markClosedByUser, true);
}

function post(event: ReplayWorkerEvent): void {
  scope.postMessage(event);
}

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export {};
