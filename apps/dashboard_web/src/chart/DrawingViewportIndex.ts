import {
  DRAWING_INDEX_BUCKET_NS,
  DRAWING_INDEX_MAX_BUCKET_SPAN,
  DRAWING_VIEWPORT_MARGIN_RATIO,
  MAX_VISIBLE_DRAWINGS
} from "./performanceLimits";
import type { DrawingState } from "./chartState";
import type { VisibleTimeRangeNs } from "./ChartAdapter";

interface IndexedDrawing {
  state: DrawingState;
  ordinal: number;
  zIndex: number;
}

interface DrawingTimeBounds {
  from: number;
  to: number;
}

export interface DrawingQueryResult {
  drawings: DrawingState[];
  totalCount: number;
  matchedCount: number;
}

export class DrawingViewportIndex {
  private readonly buckets = new Map<number, IndexedDrawing[]>();
  private readonly global: IndexedDrawing[] = [];
  private total = 0;

  get size(): number {
    return this.total;
  }

  replace(drawings: Iterable<DrawingState>): void {
    this.buckets.clear();
    this.global.length = 0;
    this.total = 0;

    let ordinal = 0;
    for (const state of drawings) {
      const entry: IndexedDrawing = {
        state,
        ordinal,
        zIndex: finiteNumber(state.payload.z_index, 0)
      };
      ordinal += 1;
      this.total += 1;

      const bounds = drawingTimeBounds(state);
      if (!bounds || isDynamicDrawing(state)) {
        this.global.push(entry);
        continue;
      }

      const firstBucket = bucketFor(bounds.from);
      const lastBucket = bucketFor(bounds.to);
      const span = lastBucket - firstBucket + 1;
      if (span <= 0 || span > DRAWING_INDEX_MAX_BUCKET_SPAN) {
        this.global.push(entry);
        continue;
      }

      for (let bucket = firstBucket; bucket <= lastBucket; bucket += 1) {
        const entries = this.buckets.get(bucket);
        if (entries) entries.push(entry);
        else this.buckets.set(bucket, [entry]);
      }
    }
  }

  query(
    range: VisibleTimeRangeNs | null,
    maximumDrawings = MAX_VISIBLE_DRAWINGS
  ): DrawingQueryResult {
    if (this.total === 0) {
      return { drawings: [], totalCount: 0, matchedCount: 0 };
    }

    const limit = Math.max(1, Math.floor(maximumDrawings));
    const selected = new Map<string, IndexedDrawing>();
    const globalStart = Math.max(0, this.global.length - limit);
    for (let index = globalStart; index < this.global.length; index += 1) {
      const entry = this.global[index];
      if (entry) selected.set(entry.state.drawingId, entry);
    }

    if (range) {
      const span = Math.max(1, range.toNs - range.fromNs);
      const margin = span * DRAWING_VIEWPORT_MARGIN_RATIO;
      const fromBucket = bucketFor(range.fromNs - margin);
      const toBucket = bucketFor(range.toNs + margin);
      for (let bucket = fromBucket; bucket <= toBucket; bucket += 1) {
        const entries = this.buckets.get(bucket);
        if (!entries) continue;
        for (const entry of entries) selected.set(entry.state.drawingId, entry);
      }
    } else {
      const keys = [...this.buckets.keys()].sort((left, right) => right - left);
      for (const key of keys.slice(0, 4)) {
        for (const entry of this.buckets.get(key) ?? []) {
          selected.set(entry.state.drawingId, entry);
        }
      }
    }

    const matchedCount = selected.size;
    const recent = [...selected.values()].sort((left, right) => left.ordinal - right.ordinal);
    const limited = recent.length <= limit
      ? recent
      : recent.slice(recent.length - limit);
    limited.sort((left, right) => {
      if (left.zIndex !== right.zIndex) return left.zIndex - right.zIndex;
      return left.ordinal - right.ordinal;
    });

    return {
      drawings: limited.map(entry => entry.state),
      totalCount: this.total,
      matchedCount
    };
  }
}

export function drawingTimeBounds(state: DrawingState): DrawingTimeBounds | null {
  const drawing = state.payload;
  const kind = String(drawing.kind ?? "");

  if (kind === "horizontal_line") return null;
  if (kind === "trend_line" || kind === "rectangle") {
    return pointPairBounds(drawing.start, drawing.end);
  }
  if (kind === "marker") return singleTimeBounds(drawing.time_ns);
  if (kind === "label") return pointTimeBounds(drawing.anchor);
  if (kind === "risk_reward" || kind === "broker_trade") {
    const entry = finiteNullableNumber(drawing.entry_time_ns);
    const exit = finiteNullableNumber(drawing.exit_time_ns);
    if (entry === null) return null;
    return normalizeBounds(entry, exit ?? entry);
  }

  const direct = singleTimeBounds(drawing.time_ns);
  if (direct) return direct;
  const pair = pointPairBounds(drawing.start, drawing.end);
  if (pair) return pair;
  return pointTimeBounds(drawing.anchor);
}

function isDynamicDrawing(state: DrawingState): boolean {
  const drawing = state.payload;
  const kind = String(drawing.kind ?? "");
  if (kind !== "broker_trade" && kind !== "risk_reward") return false;
  return String(drawing.status ?? "") === "open";
}

function pointPairBounds(startValue: unknown, endValue: unknown): DrawingTimeBounds | null {
  const start = pointTime(startValue);
  const end = pointTime(endValue);
  if (start === null || end === null) return null;
  return normalizeBounds(start, end);
}

function pointTimeBounds(value: unknown): DrawingTimeBounds | null {
  const time = pointTime(value);
  return time === null ? null : { from: time, to: time };
}

function pointTime(value: unknown): number | null {
  if (!value || typeof value !== "object") return null;
  return finiteNullableNumber((value as Record<string, unknown>).time_ns);
}

function singleTimeBounds(value: unknown): DrawingTimeBounds | null {
  const time = finiteNullableNumber(value);
  return time === null ? null : { from: time, to: time };
}

function normalizeBounds(left: number, right: number): DrawingTimeBounds {
  return { from: Math.min(left, right), to: Math.max(left, right) };
}

function bucketFor(timeNs: number): number {
  return Math.floor(timeNs / DRAWING_INDEX_BUCKET_NS);
}

function finiteNullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function finiteNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}
