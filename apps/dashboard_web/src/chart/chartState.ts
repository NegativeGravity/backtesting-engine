import type { ReplayTimelineItem } from "../lib/types";

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

export interface ChartMutationSummary {
  chartCommands: number;
  seriesPoints: number;
  seriesChanged: boolean;
  drawingsChanged: boolean;
}

const MAX_POINTS_PER_SERIES = 12_000;
const MAX_ACTIVE_DRAWINGS = 3_000;

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

  if (points.length > MAX_POINTS_PER_SERIES) {
    points.splice(0, points.length - MAX_POINTS_PER_SERIES);
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
  const overflow = state.drawings.size - MAX_ACTIVE_DRAWINGS;
  if (overflow <= 0) return;
  let remaining = overflow;
  for (const drawingId of state.drawings.keys()) {
    state.drawings.delete(drawingId);
    remaining -= 1;
    if (remaining === 0) break;
  }
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
