import type { CanvasDrawingPrimitive, CanvasTextPrimitive } from "../lib/drawingProtocol";
import type { ChartCoordinates } from "./ChartAdapter";
import type { DrawingState } from "./chartState";

const DEFAULT_MAX_DRAWINGS = 1_500;
const VIEWPORT_MARGIN = 120;
const TEHRAN_TRADE_TIME_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZone: "Asia/Tehran",
  timeZoneName: "short"
});

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

    if (kind === "broker_trade") {
      appendBrokerTradePrimitives(output, drawing, coordinates, tickSize, width, height);
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


function appendBrokerTradePrimitives(
  output: CanvasDrawingPrimitive[],
  drawing: Record<string, unknown>,
  coordinates: ChartCoordinates,
  tickSize: number,
  width: number,
  height: number
): void {
  const entryTime = Number(drawing.entry_time_ns);
  const exitTime = Number(drawing.exit_time_ns);
  const entryTicks = Number(drawing.entry_price_ticks);
  const exitTicks = Number(drawing.exit_price_ticks);
  if (![entryTime, exitTime, entryTicks, exitTicks].every(Number.isFinite)) return;

  const x1 = coordinates.timeToX(entryTime);
  const x2 = coordinates.timeToX(Math.max(entryTime, exitTime));
  const entry = coordinates.priceToY(entryTicks * tickSize);
  const exit = coordinates.priceToY(exitTicks * tickSize);
  if (x1 === null || x2 === null || entry === null || exit === null) return;
  if (![x1, x2, entry, exit].every(Number.isFinite)) return;

  const x = Math.min(x1, x2);
  const right = Math.max(x1, x2);
  const boxWidth = Math.max(26, right - x);
  const side = String(drawing.side ?? "long") === "short" ? "short" : "long";
  const status = String(drawing.status ?? "closed");
  const exitKind = String(drawing.exit_kind ?? "manual");
  const netPnl = Number(drawing.net_pnl ?? 0);
  const stopTicks = nullableFiniteNumber(drawing.stop_price_ticks);
  const targetTicks = nullableFiniteNumber(drawing.target_price_ticks);
  const stop = stopTicks === null ? null : coordinates.priceToY(stopTicks * tickSize);
  const target = targetTicks === null ? null : coordinates.priceToY(targetTicks * tickSize);
  const statusColor = brokerStatusColor(exitKind, netPnl);
  const riskColor = "#ff5c73";
  const rewardColor = "#16c79a";

  if (stop !== null && Number.isFinite(stop)) {
    const riskRect = normalizedRect(x, entry, x + boxWidth, stop);
    if (rectIntersectsViewport(riskRect.x, riskRect.y, riskRect.width, riskRect.height, width, height)) {
      output.push({
        kind: "rect",
        ...riskRect,
        fill: riskColor,
        fillAlpha: 0.19,
        stroke: exitKind === "stop_loss" ? riskColor : "rgba(255, 92, 115, 0.58)",
        strokeWidth: exitKind === "stop_loss" ? 1.5 : 0.8,
        dash: []
      });
    }
  }

  if (target !== null && Number.isFinite(target)) {
    const rewardRect = normalizedRect(x, entry, x + boxWidth, target);
    if (rectIntersectsViewport(rewardRect.x, rewardRect.y, rewardRect.width, rewardRect.height, width, height)) {
      output.push({
        kind: "rect",
        ...rewardRect,
        fill: rewardColor,
        fillAlpha: 0.16,
        stroke: exitKind === "take_profit" ? rewardColor : "rgba(22, 199, 154, 0.56)",
        strokeWidth: exitKind === "take_profit" ? 1.5 : 0.8,
        dash: []
      });
    }
  }

  if (stop === null && target === null) {
    const pnlRect = normalizedRect(x, entry, x + boxWidth, exit);
    if (rectIntersectsViewport(pnlRect.x, pnlRect.y, pnlRect.width, pnlRect.height, width, height)) {
      output.push({
        kind: "rect",
        ...pnlRect,
        fill: statusColor,
        fillAlpha: 0.14,
        stroke: statusColor,
        strokeWidth: 1,
        dash: []
      });
    }
  }

  pushHorizontalLine(output, x, x + boxWidth, entry, "#4f8cff", 1.25, []);
  if (stop !== null && Number.isFinite(stop)) {
    pushHorizontalLine(output, x, x + boxWidth, stop, riskColor, 1, [7, 4]);
  }
  if (target !== null && Number.isFinite(target)) {
    pushHorizontalLine(output, x, x + boxWidth, target, rewardColor, 1, [7, 4]);
  }
  pushHorizontalLine(output, Math.max(x, right - 12), right + 10, exit, statusColor, 1.8, []);

  if (pointInsideViewport(right, exit, width, height)) {
    output.push({
      kind: "polygon",
      points: [right, exit, right + 8, exit - 6, right + 8, exit + 6],
      fill: statusColor
    });
  }

  const topReference = Math.min(
    entry,
    target !== null && Number.isFinite(target) ? target : exit,
    stop !== null && Number.isFinite(stop) ? stop : exit
  );
  const bottomReference = Math.max(
    entry,
    target !== null && Number.isFinite(target) ? target : exit,
    stop !== null && Number.isFinite(stop) ? stop : exit
  );
  const statusLabel = `${side.toUpperCase()} · ${brokerStatusLabel(exitKind, status)} · PnL ${formatSigned(netPnl)}`;
  output.push(labelPrimitive(x + 6, clampCoordinate(topReference + 16, 18, height - 8), statusLabel, statusColor));
  output.push(labelPrimitive(
    x + 6,
    clampCoordinate(entry - 7, 18, height - 8),
    `OPEN ${formatTimeNs(entryTime)} @ ${formatPriceTicks(entryTicks, tickSize)}`,
    "#8db4ff"
  ));

  const exitPrefix = status === "open" ? "LIVE" : "CLOSE";
  const closeY = clampCoordinate(exit + (exit <= entry ? -7 : 17), 18, height - 8);
  output.push(labelPrimitive(
    Math.max(x + 6, right - 190),
    closeY,
    `${exitPrefix} ${formatTimeNs(exitTime)} @ ${formatPriceTicks(exitTicks, tickSize)}`,
    statusColor
  ));

  if (stop !== null && Number.isFinite(stop)) {
    output.push(textPrimitive(x + boxWidth + 5, clampCoordinate(stop + 4, 18, height - 8), `SL ${formatPriceTicks(stopTicks ?? 0, tickSize)}`, riskColor));
  }
  if (target !== null && Number.isFinite(target)) {
    output.push(textPrimitive(x + boxWidth + 5, clampCoordinate(target + 4, 18, height - 8), `TP ${formatPriceTicks(targetTicks ?? 0, tickSize)}`, rewardColor));
  }

  if (drawing.intrabar_ambiguous === true) {
    output.push(labelPrimitive(
      x + 6,
      clampCoordinate(bottomReference + 18, 18, height - 8),
      "INTRABAR AMBIGUOUS",
      "#ffbf69"
    ));
  }
}

function pushHorizontalLine(
  output: CanvasDrawingPrimitive[],
  x1: number,
  x2: number,
  y: number,
  color: string,
  width: number,
  lineDash: number[]
): void {
  output.push({ kind: "line", x1, y1: y, x2, y2: y, color, width, dash: lineDash });
}

function labelPrimitive(x: number, y: number, text: string, color: string): CanvasTextPrimitive {
  return {
    ...textPrimitive(x, y, text, color),
    background: "rgba(6, 10, 15, 0.88)"
  };
}

function brokerStatusLabel(exitKind: string, status: string): string {
  if (status === "open" || exitKind === "open") return "OPEN";
  if (exitKind === "take_profit") return "TP HIT";
  if (exitKind === "stop_loss") return "SL HIT";
  if (exitKind === "liquidation") return "LIQUIDATED";
  return "CLOSED";
}

function brokerStatusColor(exitKind: string, netPnl: number): string {
  if (exitKind === "take_profit") return "#16c79a";
  if (exitKind === "stop_loss" || exitKind === "liquidation") return "#ff5c73";
  if (exitKind === "open") return "#4f8cff";
  return netPnl >= 0 ? "#16c79a" : "#ff5c73";
}

function formatSigned(value: number): string {
  if (!Number.isFinite(value)) return "0.00";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

function formatPriceTicks(value: number, tickSize: number): string {
  const price = value * tickSize;
  if (!Number.isFinite(price)) return "—";
  const digits = tickSize >= 1 ? 0 : Math.min(8, Math.max(2, Math.ceil(-Math.log10(tickSize))));
  return price.toFixed(digits);
}

function formatTimeNs(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return TEHRAN_TRADE_TIME_FORMATTER.format(
    new Date(value / 1_000_000)
  ).replace(",", "");
}

function nullableFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function clampCoordinate(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
