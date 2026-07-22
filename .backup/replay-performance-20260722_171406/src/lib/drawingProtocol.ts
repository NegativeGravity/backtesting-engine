export interface CanvasLinePrimitive {
  kind: "line";
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
  width: number;
  dash: number[];
}

export interface CanvasRectPrimitive {
  kind: "rect";
  x: number;
  y: number;
  width: number;
  height: number;
  fill: string | null;
  fillAlpha: number;
  stroke: string | null;
  strokeWidth: number;
  dash: number[];
}

export interface CanvasPolygonPrimitive {
  kind: "polygon";
  points: number[];
  fill: string;
}

export interface CanvasTextPrimitive {
  kind: "text";
  x: number;
  y: number;
  text: string;
  color: string;
  background: string | null;
  font: string;
  align: CanvasTextAlign;
}

export type CanvasDrawingPrimitive =
  | CanvasLinePrimitive
  | CanvasRectPrimitive
  | CanvasPolygonPrimitive
  | CanvasTextPrimitive;

export type DrawingWorkerCommand =
  | {
      type: "initialize";
      canvas: OffscreenCanvas;
      width: number;
      height: number;
      devicePixelRatio: number;
    }
  | {
      type: "resize";
      width: number;
      height: number;
      devicePixelRatio: number;
    }
  | {
      type: "draw";
      revision: number;
      primitives: CanvasDrawingPrimitive[];
    }
  | { type: "clear" };

export type DrawingWorkerEvent =
  | { type: "ready" }
  | { type: "drawn"; revision: number }
  | { type: "error"; detail: string };
