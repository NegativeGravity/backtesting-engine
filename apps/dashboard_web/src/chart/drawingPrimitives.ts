import type { CanvasDrawingPrimitive, CanvasTextPrimitive } from "../lib/drawingProtocol";
import type { ChartCoordinates } from "./ChartAdapter";
import type { DrawingState } from "./chartState";

const DEFAULT_MAX_DRAWINGS = 1_500;
const VIEWPORT_MARGIN = 120;

export function buildDrawingPrimitives(
  drawings: Iterable<DrawingState>,
  coordinates: ChartCoordinates,
  tickSize: number,
  width: number,
  height: number,
  maximumDrawings = DEFAULT_MAX_DRAWINGS
): CanvasDrawingPrimitive[] {
  const candidates = Array.from(drawings).slice(-maximumDrawings);
  const output: CanvasDrawingPrimitive[] = [];

  for (const state of candidates) {
    const drawing = state.payload;
    if (drawing.visible === false) continue;
    const kind = String(drawing.kind ?? "");

    if (kind === "trend_line") {
      const start = asPoint(drawing.start);
      const end = asPoint(drawing.end);
      if (!start || !end) continue;
      const x1 = coordinates.timeToX(start.timeNs);
      const x2 = coordinates.timeToX(end.timeNs);
      const y1 = coordinates.priceToY(start.priceTicks * tickSize);
      const y2 = coordinates.priceToY(end.priceTicks * tickSize);
      if (x1 === null || x2 === null || y1 === null || y2 === null) continue;
      if (![x1, x2, y1, y2].every(Number.isFinite)) continue;
      if (!lineIntersectsViewport(x1, y1, x2, y2, width, height)) continue;
      const appearance = asAppearance(drawing.appearance);
      output.push({
        kind: "line",
        x1,
        y1,
        x2,
        y2,
        color: appearance.color,
        width: appearance.width,
        dash: dash(appearance.style)
      });
      continue;
    }

    if (kind === "horizontal_line") {
      const y = coordinates.priceToY(Number(drawing.price_ticks) * tickSize);
      if (!isFiniteNumber(y) || y < -VIEWPORT_MARGIN || y > height + VIEWPORT_MARGIN) continue;
      const appearance = asAppearance(drawing.appearance);
      output.push({
        kind: "line",
        x1: 0,
        y1: y,
        x2: width,
        y2: y,
        color: appearance.color,
        width: appearance.width,
        dash: dash(appearance.style)
      });
      const label = safeText(drawing.label);
      if (label) {
        output.push(textPrimitive(8, y - 6, label, appearance.color));
      }
      continue;
    }

    if (kind === "rectangle") {
      const start = asPoint(drawing.start);
      const end = asPoint(drawing.end);
      if (!start || !end) continue;
      const x1 = coordinates.timeToX(start.timeNs);
      const x2 = coordinates.timeToX(end.timeNs);
      const y1 = coordinates.priceToY(start.priceTicks * tickSize);
      const y2 = coordinates.priceToY(end.priceTicks * tickSize);
      if (x1 === null || x2 === null || y1 === null || y2 === null) continue;
      if (![x1, x2, y1, y2].every(Number.isFinite)) continue;
      const rect = normalizedRect(x1, y1, x2, y2);
      if (!rectIntersectsViewport(rect.x, rect.y, rect.width, rect.height, width, height)) continue;
      const border = asAppearance(drawing.border);
      const fill = asFill(drawing.fill);
      output.push({
        kind: "rect",
        ...rect,
        fill: fill.color,
        fillAlpha: fill.opacity,
        stroke: border.color,
        strokeWidth: border.width,
        dash: dash(border.style)
      });
      continue;
    }

    if (kind === "marker") {
      const x = coordinates.timeToX(Number(drawing.time_ns));
      const priceTicks = drawing.price_ticks;
      const y = priceTicks === null || priceTicks === undefined
        ? null
        : coordinates.priceToY(Number(priceTicks) * tickSize);
      if (x === null || y === null || !Number.isFinite(x) || !Number.isFinite(y)) continue;
      if (!pointInsideViewport(x, y, width, height)) continue;
      const position = String(drawing.position ?? "above_bar");
      const offset = position === "below_bar" ? 13 : -13;
      const markerY = y + offset;
      output.push({
        kind: "polygon",
        points: position === "below_bar"
          ? [x, markerY - 8, x + 7, markerY + 4, x - 7, markerY + 4]
          : [x, markerY + 8, x + 7, markerY - 4, x - 7, markerY - 4],
        fill: safeColor(drawing.color, "#d7deea")
      });
      const label = safeText(drawing.text);
      if (label) output.push(textPrimitive(x + 10, markerY + 4, label, safeColor(drawing.color, "#d7deea")));
      continue;
    }

    if (kind === "label") {
      const anchor = asPoint(drawing.anchor);
      if (!anchor) continue;
      const x = coordinates.timeToX(anchor.timeNs);
      const y = coordinates.priceToY(anchor.priceTicks * tickSize);
      if (x === null || y === null || !Number.isFinite(x) || !Number.isFinite(y)) continue;
      if (!pointInsideViewport(x, y, width, height)) continue;
      const label = safeText(drawing.text);
      if (!label) continue;
      output.push({
        ...textPrimitive(x, y - 4, label, safeColor(drawing.text_color, "#d7deea")),
        background: safeColor(drawing.background_color, "rgba(12, 16, 22, 0.9)")
      });
      continue;
    }

    if (kind === "risk_reward") {
      const entryTime = Number(drawing.entry_time_ns);
      const exitTime = Number(drawing.exit_time_ns ?? entryTime + 30 * 60 * 1_000_000_000);
      const x1 = coordinates.timeToX(entryTime);
      const x2 = coordinates.timeToX(exitTime);
      const entry = coordinates.priceToY(Number(drawing.entry_price_ticks) * tickSize);
      const stop = coordinates.priceToY(Number(drawing.stop_price_ticks) * tickSize);
      const target = coordinates.priceToY(Number(drawing.target_price_ticks) * tickSize);
      if (x1 === null || x2 === null || entry === null || stop === null || target === null) continue;
      if (![x1, x2, entry, stop, target].every(Number.isFinite)) continue;
      const x = Math.min(x1, x2);
      const boxWidth = Math.max(20, Math.abs(x2 - x1));
      const risk = asFill(drawing.risk_fill);
      const reward = asFill(drawing.reward_fill);
      const riskRect = normalizedRect(x, entry, x + boxWidth, stop);
      const rewardRect = normalizedRect(x, entry, x + boxWidth, target);
      if (
        !rectIntersectsViewport(riskRect.x, riskRect.y, riskRect.width, riskRect.height, width, height) &&
        !rectIntersectsViewport(rewardRect.x, rewardRect.y, rewardRect.width, rewardRect.height, width, height)
      ) continue;
      output.push({ kind: "rect", ...riskRect, fill: risk.color, fillAlpha: risk.opacity, stroke: null, strokeWidth: 0, dash: [] });
      output.push({ kind: "rect", ...rewardRect, fill: reward.color, fillAlpha: reward.opacity, stroke: null, strokeWidth: 0, dash: [] });
      for (const [price, appearanceValue] of [
        [entry, drawing.entry_line],
        [stop, drawing.stop_line],
        [target, drawing.target_line]
      ] as const) {
        const appearance = asAppearance(appearanceValue);
        output.push({
          kind: "line",
          x1: x,
          y1: price,
          x2: x + boxWidth,
          y2: price,
          color: appearance.color,
          width: appearance.width,
          dash: dash(appearance.style)
        });
      }
      const label = safeText(drawing.label);
      if (label) output.push(textPrimitive(x + 6, Math.min(entry, target) + 16, label, "#d8e0eb"));
    }
  }

  return output;
}

function textPrimitive(x: number, y: number, text: string, color: string): CanvasTextPrimitive {
  return {
    kind: "text",
    x,
    y,
    text,
    color,
    background: null,
    font: "600 11px Inter, ui-sans-serif, system-ui, sans-serif",
    align: "left"
  };
}

function asPoint(value: unknown): { timeNs: number; priceTicks: number } | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const timeNs = Number(record.time_ns);
  const priceTicks = Number(record.price_ticks);
  if (!Number.isFinite(timeNs) || !Number.isFinite(priceTicks)) return null;
  return { timeNs, priceTicks };
}

function asAppearance(value: unknown): { color: string; width: number; style: string } {
  const record = value && typeof value === "object" ? value as Record<string, unknown> : {};
  return {
    color: safeColor(record.color, "#d7deea"),
    width: clamp(Number(record.width), 0.5, 8, 1),
    style: String(record.style ?? "solid")
  };
}

function asFill(value: unknown): { color: string; opacity: number } {
  const record = value && typeof value === "object" ? value as Record<string, unknown> : {};
  return {
    color: safeColor(record.color, "#4c8dff"),
    opacity: clamp(Number(record.opacity), 0, 1, 0.2)
  };
}

function safeColor(value: unknown, fallback: string): string {
  const color = String(value ?? "").trim();
  return color.length > 0 && color.length <= 80 ? color : fallback;
}

function safeText(value: unknown): string {
  return String(value ?? "").slice(0, 160);
}

function dash(style: string): number[] {
  if (style === "dashed") return [8, 5];
  if (style === "dotted") return [2, 4];
  return [];
}

function normalizedRect(x1: number, y1: number, x2: number, y2: number) {
  return {
    x: Math.min(x1, x2),
    y: Math.min(y1, y2),
    width: Math.abs(x2 - x1),
    height: Math.abs(y2 - y1)
  };
}

function isFiniteNumber(value: number | null): value is number {
  return value !== null && Number.isFinite(value);
}

function pointInsideViewport(x: number, y: number, width: number, height: number): boolean {
  return x >= -VIEWPORT_MARGIN && x <= width + VIEWPORT_MARGIN && y >= -VIEWPORT_MARGIN && y <= height + VIEWPORT_MARGIN;
}

function lineIntersectsViewport(x1: number, y1: number, x2: number, y2: number, width: number, height: number): boolean {
  const minX = Math.min(x1, x2);
  const maxX = Math.max(x1, x2);
  const minY = Math.min(y1, y2);
  const maxY = Math.max(y1, y2);
  return maxX >= -VIEWPORT_MARGIN && minX <= width + VIEWPORT_MARGIN && maxY >= -VIEWPORT_MARGIN && minY <= height + VIEWPORT_MARGIN;
}

function rectIntersectsViewport(x: number, y: number, rectWidth: number, rectHeight: number, width: number, height: number): boolean {
  return x + rectWidth >= -VIEWPORT_MARGIN && x <= width + VIEWPORT_MARGIN && y + rectHeight >= -VIEWPORT_MARGIN && y <= height + VIEWPORT_MARGIN;
}

function clamp(value: number, minimum: number, maximum: number, fallback: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.min(maximum, Math.max(minimum, value));
}
