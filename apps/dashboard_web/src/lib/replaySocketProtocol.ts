import type { FrameSchedulerStats, RenderProfile } from "./frameScheduler";
import type { ReplayControlCommand, SocketMessage } from "./types";

export type ReplayWorkerStatus = "connecting" | "connected" | "disconnected" | "error";

export type ReplayWorkerCommand =
  | {
      type: "connect";
      url: string;
      profile: RenderProfile;
      hidden: boolean;
    }
  | { type: "send"; command: ReplayControlCommand }
  | { type: "configure"; profile: RenderProfile; hidden: boolean }
  | { type: "ack" }
  | { type: "close" };

export type ReplayWorkerEvent =
  | { type: "status"; status: ReplayWorkerStatus }
  | { type: "message"; message: SocketMessage }
  | { type: "stats"; stats: FrameSchedulerStats }
  | { type: "fatal"; detail: string };
