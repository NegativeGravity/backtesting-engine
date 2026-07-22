import type { ReplayTimelineItem } from "../lib/types";
import {
  MAX_ACTIVE_STRATEGY_DRAWINGS,
  SERIES_POINT_HIGH_WATER,
  SERIES_POINT_TARGET
} from "./performanceLimits";

export interface SeriesDefinition {
  seriesId: string;
  title: string;
  kind: string;
  color: string;
  lineWidth: number;
  visible: boolean;
}

export interface ScalarPoint {
  timeNs: number;
  value: number;
}

export interface DrawingState {
  drawingId: string;
  revision: number;
  payload: Record<string, unknown>;
}

export interface MaterializedChartState {
  series: Map<string, SeriesDefinition>;
  points: Map<string, ScalarPoint[]>;
  drawings: Map<string, DrawingState>;
}


export interface ChartWindowPruneSummary {
  pointsRemoved: number;
  drawingsRemoved: number;
}

export interface ChartMutationSummary {
  chartCommands: number;
  seriesPoints: number;
  seriesChanged: boolean;
  drawingsChanged: boolean;
}


export function emptyChartState(): MaterializedChartState {
  return {
    series: new Map(),
    points: new Map(),
    drawings: new Map()
  };
}

export function cloneChartState(state: MaterializedChartState): MaterializedChartState {
  return {
    series: new Map(state.series),
    points: new Map([...state.points].map(([seriesId, points]) => [seriesId, [...points]])),
    drawings: new Map(state.drawings)
  };
}

export function materializeChartState(items: ReplayTimelineItem[]): MaterializedChartState {
  const state = emptyChartState();
  applyChartCommandsMutable(state, items);
  return state;
}

export function applyChartCommands(
  state: MaterializedChartState,
  items: ReplayTimelineItem[]
): MaterializedChartState {
  const next = cloneChartState(state);
  applyChartCommandsMutable(next, items);
  return next;
}

export function applyChartCommandsMutable(
  state: MaterializedChartState,
  items: ReplayTimelineItem[]
): ChartMutationSummary {
  const summary: ChartMutationSummary = {
    chartCommands: 0,
    seriesPoints: 0,
    seriesChanged: false,
    drawingsChanged: false
  };

  for (const item of items) {
    if (item.kind !== "chart_command") continue;
    summary.chartCommands += 1;
    const command = item.payload;
    const type = String(command.command_type ?? "");

    if (type === "append_series_point") {
      if (appendSeriesPointMutable(state, command)) summary.seriesPoints += 1;
      continue;
    }

    if (type === "declare_series") {
      declareSeriesMutable(state, command);
      summary.seriesChanged = true;
      continue;
    }

    if (type === "upsert_drawing") {
      if (upsertDrawingMutable(state, command)) summary.drawingsChanged = true;
      continue;
    }

    if (type === "delete_drawing") {
      if (state.drawings.delete(String(command.drawing_id))) summary.drawingsChanged = true;
      continue;
    }

    if (type === "clear_layer") {
      const layerId = String(command.layer_id);
      for (const [drawingId, drawing] of state.drawings) {
        if (drawing.payload.layer_id === layerId) {
          state.drawings.delete(drawingId);
          summary.drawingsChanged = true;
        }
      }
    }
  }

  if (summary.drawingsChanged) trimDrawings(state);
  return summary;
}

export function pruneChartStateToWindow(
  state: MaterializedChartState,
  fromTimeNs: number,
  toTimeNs: number,
  marginNs = 0
): ChartWindowPruneSummary {
  if (!Number.isFinite(fromTimeNs) || !Number.isFinite(toTimeNs)) {
    return { pointsRemoved: 0, drawingsRemoved: 0 };
  }

  const boundedFrom = Math.min(fromTimeNs, toTimeNs) - Math.max(0, marginNs);
  const boundedTo = Math.max(fromTimeNs, toTimeNs) + Math.max(0, marginNs);
  let pointsRemoved = 0;
  let drawingsRemoved = 0;

  for (const [seriesId, points] of state.points) {
    if (points.length === 0) continue;
    const firstInside = lowerBoundPoint(points, boundedFrom);
    const keepFrom = Math.max(0, firstInside - 1);
    const keepTo = upperBoundPoint(points, boundedTo);
    if (keepFrom === 0 && keepTo === points.length) continue;
    const next = points.slice(keepFrom, keepTo);
    pointsRemoved += points.length - next.length;
    state.points.set(seriesId, next);
  }

  for (const [drawingId, drawing] of state.drawings) {
    const bounds = drawingTimeBounds(drawing.payload);
    if (!bounds) continue;
    if (bounds.to >= boundedFrom && bounds.from <= boundedTo) continue;
    state.drawings.delete(drawingId);
    drawingsRemoved += 1;
  }

  return { pointsRemoved, drawingsRemoved };
}

export function applyChartCommand(
  state: MaterializedChartState,
  command: Record<string, unknown>
): void {
  applyChartCommandsMutable(state, [
    {
      sequence: 0,
      time_ns: 0,
      kind: "chart_command",
      payload: command
    }
  ]);
}

function declareSeriesMutable(
  state: MaterializedChartState,
  command: Record<string, unknown>
): void {
  const seriesValue = command.series;
  if (!seriesValue || typeof seriesValue !== "object") return;
  const series = seriesValue as Record<string, unknown>;
  const seriesId = String(series.series_id ?? "");
  if (!seriesId) return;
  state.series.set(seriesId, {
    seriesId,
    title: String(series.title ?? seriesId),
    kind: String(series.kind ?? "line"),
    color: String(series.color ?? "#4c8dff"),
    lineWidth: Number(series.line_width ?? 1),
    visible: series.visible !== false
  });
  if (!state.points.has(seriesId)) state.points.set(seriesId, []);
}

function appendSeriesPointMutable(
  state: MaterializedChartState,
  command: Record<string, unknown>
): boolean {
  const seriesId = String(command.series_id ?? "");
  const pointValue = command.point;
  if (!seriesId || !pointValue || typeof pointValue !== "object") return false;
  const point = pointValue as Record<string, unknown>;
  if (point.point_type !== "scalar") return false;

  const timeNs = Number(point.time_ns);
  const value = Number(point.value);
  if (!Number.isFinite(timeNs) || !Number.isFinite(value)) return false;

  const points = state.points.get(seriesId) ?? [];
  const last = points.at(-1);
  if (last?.timeNs === timeNs) {
    points[points.length - 1] = { timeNs, value };
  } else if (!last || timeNs > last.timeNs) {
    points.push({ timeNs, value });
  } else {
    const index = lowerBoundPoint(points, timeNs);
    if (points[index]?.timeNs === timeNs) points[index] = { timeNs, value };
    else points.splice(index, 0, { timeNs, value });
  }

  if (points.length > SERIES_POINT_HIGH_WATER) {
    points.splice(0, points.length - SERIES_POINT_TARGET);
  }
  state.points.set(seriesId, points);
  return true;
}

function upsertDrawingMutable(
  state: MaterializedChartState,
  command: Record<string, unknown>
): boolean {
  const drawingValue = command.drawing;
  if (!drawingValue || typeof drawingValue !== "object") return false;
  const drawing = drawingValue as Record<string, unknown>;
  const drawingId = String(drawing.drawing_id ?? "");
  if (!drawingId) return false;
  const revision = Number(drawing.revision ?? 0);
  const current = state.drawings.get(drawingId);
  if (current && revision < current.revision) return false;

  if (current) state.drawings.delete(drawingId);
  state.drawings.set(drawingId, { drawingId, revision, payload: drawing });
  return true;
}

function trimDrawings(state: MaterializedChartState): void {
  const overflow = state.drawings.size - MAX_ACTIVE_STRATEGY_DRAWINGS;
  if (overflow <= 0) return;
  let remaining = overflow;
  for (const drawingId of state.drawings.keys()) {
    state.drawings.delete(drawingId);
    remaining -= 1;
    if (remaining === 0) break;
  }
}

function drawingTimeBounds(
  drawing: Record<string, unknown>
): { from: number; to: number } | null {
  const kind = String(drawing.kind ?? "");
  if (kind === "horizontal_line") return null;
  if (kind === "trend_line" || kind === "rectangle") {
    return pointPairBounds(drawing.start, drawing.end);
  }
  if (kind === "marker") return singleTimeBounds(drawing.time_ns);
  if (kind === "label") return pointTimeBounds(drawing.anchor);
  if (kind === "risk_reward" || kind === "broker_trade") {
    const entry = finiteTime(drawing.entry_time_ns);
    if (entry === null) return null;
    const exit = finiteTime(drawing.exit_time_ns);
    if (exit === null) return null;
    return normalizeBounds(entry, exit);
  }
  return singleTimeBounds(drawing.time_ns)
    ?? pointPairBounds(drawing.start, drawing.end)
    ?? pointTimeBounds(drawing.anchor);
}

function pointPairBounds(startValue: unknown, endValue: unknown): { from: number; to: number } | null {
  const start = pointTime(startValue);
  const end = pointTime(endValue);
  return start === null || end === null ? null : normalizeBounds(start, end);
}

function pointTimeBounds(value: unknown): { from: number; to: number } | null {
  const time = pointTime(value);
  return time === null ? null : { from: time, to: time };
}

function pointTime(value: unknown): number | null {
  if (!value || typeof value !== "object") return null;
  return finiteTime((value as Record<string, unknown>).time_ns);
}

function singleTimeBounds(value: unknown): { from: number; to: number } | null {
  const time = finiteTime(value);
  return time === null ? null : { from: time, to: time };
}

function normalizeBounds(left: number, right: number): { from: number; to: number } {
  return { from: Math.min(left, right), to: Math.max(left, right) };
}

function finiteTime(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function upperBoundPoint(points: ScalarPoint[], timeNs: number): number {
  let low = 0;
  let high = points.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if ((points[middle]?.timeNs ?? Number.POSITIVE_INFINITY) <= timeNs) low = middle + 1;
    else high = middle;
  }
  return low;
}

function lowerBoundPoint(points: ScalarPoint[], timeNs: number): number {
  let low = 0;
  let high = points.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if ((points[middle]?.timeNs ?? Number.POSITIVE_INFINITY) < timeNs) low = middle + 1;
    else high = middle;
  }
  return low;
}
