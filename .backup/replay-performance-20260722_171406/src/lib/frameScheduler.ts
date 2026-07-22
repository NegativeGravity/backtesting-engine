export type RenderProfile = "smooth" | "balanced" | "throughput";
export type SchedulerExecutionMode = "worker" | "main";

export interface FrameSchedulerStats {
  receivedFrames: number;
  renderedFrames: number;
  mergedFrames: number;
  lastBatchSize: number;
  pendingFrames: number;
  reconnects: number;
  resyncs: number;
  executionMode: SchedulerExecutionMode;
}

export function frameIntervalMs(
  profile: RenderProfile,
  speed: number,
  documentHidden: boolean
): number {
  if (documentHidden) return 250;
  if (profile === "smooth") {
    if (speed <= 10) return 16;
    if (speed <= 50) return 24;
    if (speed <= 100) return 33;
    return 50;
  }
  if (profile === "balanced") {
    if (speed <= 10) return 24;
    if (speed <= 50) return 33;
    if (speed <= 100) return 50;
    return 66;
  }
  if (speed <= 10) return 50;
  if (speed <= 100) return 80;
  return 120;
}

export function uiFrameIntervalMs(profile: RenderProfile): number {
  if (profile === "smooth") return 100;
  if (profile === "balanced") return 150;
  return 250;
}

export function initialFrameSchedulerStats(
  executionMode: SchedulerExecutionMode = "worker"
): FrameSchedulerStats {
  return {
    receivedFrames: 0,
    renderedFrames: 0,
    mergedFrames: 0,
    lastBatchSize: 0,
    pendingFrames: 0,
    reconnects: 0,
    resyncs: 0,
    executionMode
  };
}
