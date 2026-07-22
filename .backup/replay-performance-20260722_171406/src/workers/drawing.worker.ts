import { drawCanvasPrimitives } from "../chart/drawCanvasPrimitives";
import type { CanvasDrawingPrimitive, DrawingWorkerCommand, DrawingWorkerEvent } from "../lib/drawingProtocol";

interface WorkerScope {
  postMessage(message: DrawingWorkerEvent): void;
  onmessage: ((event: MessageEvent<DrawingWorkerCommand>) => void) | null;
}

const scope = globalThis as unknown as WorkerScope;
let canvas: OffscreenCanvas | null = null;
let context: OffscreenCanvasRenderingContext2D | null = null;
let width = 0;
let height = 0;
let devicePixelRatio = 1;

scope.onmessage = event => {
  try {
    const command = event.data;
    if (command.type === "initialize") {
      canvas = command.canvas;
      context = canvas.getContext("2d", { alpha: true, desynchronized: true });
      resize(command.width, command.height, command.devicePixelRatio);
      scope.postMessage({ type: "ready" });
      return;
    }
    if (command.type === "resize") {
      resize(command.width, command.height, command.devicePixelRatio);
      return;
    }
    if (command.type === "clear") {
      clear();
      return;
    }
    draw(command.primitives);
    scope.postMessage({ type: "drawn", revision: command.revision });
  } catch (error) {
    scope.postMessage({
      type: "error",
      detail: error instanceof Error ? error.message : String(error)
    });
  }
};

function resize(nextWidth: number, nextHeight: number, nextDevicePixelRatio: number): void {
  width = Math.max(1, Math.floor(nextWidth));
  height = Math.max(1, Math.floor(nextHeight));
  devicePixelRatio = Math.max(1, Math.min(3, nextDevicePixelRatio));
  if (!canvas || !context) return;
  canvas.width = Math.max(1, Math.floor(width * devicePixelRatio));
  canvas.height = Math.max(1, Math.floor(height * devicePixelRatio));
  context.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  clear();
}

function clear(): void {
  if (!context) return;
  context.clearRect(0, 0, width, height);
}

function draw(primitives: CanvasDrawingPrimitive[]): void {
  if (!context) return;
  drawCanvasPrimitives(context, primitives, width, height);
}

export {};
