import type { SocketMessage } from "./types";

export type ReplayRenderListener = (message: SocketMessage) => void;

export class ReplayRenderStream {
  private readonly listeners = new Set<ReplayRenderListener>();

  publish(message: SocketMessage): void {
    for (const listener of this.listeners) {
      try {
        listener(message);
      } catch (error) {
        console.error("Replay render subscriber failed", error);
      }
    }
  }

  subscribe(listener: ReplayRenderListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  clear(): void {
    this.listeners.clear();
  }
}
