import type { CanvasDrawingPrimitive } from "../lib/drawingProtocol";

type DrawingContext = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

export function drawCanvasPrimitives(
  target: DrawingContext,
  primitives: CanvasDrawingPrimitive[],
  width: number,
  height: number
): void {
  target.clearRect(0, 0, width, height);
  target.save();
  target.beginPath();
  target.rect(0, 0, width, height);
  target.clip();
  for (const primitive of primitives) drawPrimitive(target, primitive);
  target.restore();
}

function drawPrimitive(target: DrawingContext, primitive: CanvasDrawingPrimitive): void {
  if (primitive.kind === "line") {
    target.save();
    target.beginPath();
    target.moveTo(primitive.x1, primitive.y1);
    target.lineTo(primitive.x2, primitive.y2);
    target.strokeStyle = primitive.color;
    target.lineWidth = primitive.width;
    target.setLineDash(primitive.dash);
    target.stroke();
    target.restore();
    return;
  }

  if (primitive.kind === "rect") {
    target.save();
    if (primitive.fill) {
      target.globalAlpha = primitive.fillAlpha;
      target.fillStyle = primitive.fill;
      target.fillRect(primitive.x, primitive.y, primitive.width, primitive.height);
      target.globalAlpha = 1;
    }
    if (primitive.stroke && primitive.strokeWidth > 0) {
      target.strokeStyle = primitive.stroke;
      target.lineWidth = primitive.strokeWidth;
      target.setLineDash(primitive.dash);
      target.strokeRect(primitive.x, primitive.y, primitive.width, primitive.height);
    }
    target.restore();
    return;
  }

  if (primitive.kind === "polygon") {
    if (primitive.points.length < 6) return;
    target.save();
    target.beginPath();
    target.moveTo(primitive.points[0] ?? 0, primitive.points[1] ?? 0);
    for (let index = 2; index < primitive.points.length; index += 2) {
      target.lineTo(primitive.points[index] ?? 0, primitive.points[index + 1] ?? 0);
    }
    target.closePath();
    target.fillStyle = primitive.fill;
    target.fill();
    target.restore();
    return;
  }

  target.save();
  target.font = primitive.font;
  target.textAlign = primitive.align;
  target.textBaseline = "alphabetic";
  const metrics = target.measureText(primitive.text);
  if (primitive.background) {
    const paddingX = 5;
    const paddingY = 4;
    const boxHeight = 18;
    target.fillStyle = primitive.background;
    target.fillRect(
      primitive.x - paddingX,
      primitive.y - boxHeight + paddingY,
      metrics.width + paddingX * 2,
      boxHeight + paddingY
    );
  }
  target.lineWidth = 3;
  target.strokeStyle = "rgba(9, 12, 17, 0.82)";
  target.strokeText(primitive.text, primitive.x, primitive.y);
  target.fillStyle = primitive.color;
  target.fillText(primitive.text, primitive.x, primitive.y);
  target.restore();
}
