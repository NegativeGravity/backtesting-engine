import type { ReplayBar } from "../lib/types";

export interface ReplayBarAppendResult {
  appended: ReplayBar[];
  replacedLast: ReplayBar | null;
  rebuildRequired: boolean;
  windowShifted: boolean;
}

export class ReplayBarBuffer {
  private readonly values: Array<ReplayBar | undefined>;
  private start = 0;
  private length = 0;

  constructor(private readonly capacity: number, initial: ReplayBar[] = []) {
    if (!Number.isInteger(capacity) || capacity <= 0) {
      throw new Error("ReplayBarBuffer capacity must be a positive integer");
    }
    this.values = new Array<ReplayBar | undefined>(capacity);
    this.replace(initial);
  }

  get size(): number {
    return this.length;
  }

  get first(): ReplayBar | null {
    return this.length === 0 ? null : this.values[this.start] ?? null;
  }

  get last(): ReplayBar | null {
    if (this.length === 0) return null;
    return this.values[this.physicalIndex(this.length - 1)] ?? null;
  }

  replace(bars: ReplayBar[]): void {
    this.values.fill(undefined);
    this.start = 0;
    this.length = 0;
    const normalized = normalizeBars(bars).slice(-this.capacity);
    for (const bar of normalized) this.pushUnchecked(bar);
  }

  prepend(bars: ReplayBar[]): boolean {
    if (bars.length === 0) return false;
    const incoming = normalizeBars(bars);
    if (incoming.length === 0) return false;
    const current = this.toArray();
    const merged = new Map<number, ReplayBar>();
    for (const bar of incoming) merged.set(bar.sequence, bar);
    for (const bar of current) merged.set(bar.sequence, bar);
    const ordered = [...merged.values()].sort((left, right) => left.sequence - right.sequence);
    const bounded = ordered.length <= this.capacity
      ? ordered
      : ordered.slice(0, this.capacity);
    const beforeFirst = this.first?.sequence ?? null;
    const beforeLast = this.last?.sequence ?? null;
    this.replace(bounded);
    return beforeFirst !== this.first?.sequence || beforeLast !== this.last?.sequence;
  }

  append(bars: ReplayBar[]): ReplayBarAppendResult {
    if (bars.length === 0) {
      return {
        appended: [],
        replacedLast: null,
        rebuildRequired: false,
        windowShifted: false
      };
    }

    const incoming = normalizeBars(bars);
    const currentLast = this.last;
    if (!currentLast) {
      this.replace(incoming);
      return {
        appended: this.toArray(),
        replacedLast: null,
        rebuildRequired: true,
        windowShifted: false
      };
    }

    if ((incoming[0]?.sequence ?? currentLast.sequence) < currentLast.sequence) {
      this.replace(mergeSnapshots(this.toArray(), incoming, this.capacity));
      return {
        appended: [],
        replacedLast: null,
        rebuildRequired: true,
        windowShifted: false
      };
    }

    const firstBefore = this.first?.sequence ?? null;
    const appended: ReplayBar[] = [];
    let replacedLast: ReplayBar | null = null;

    for (const bar of incoming) {
      const last = this.last;
      if (!last) {
        this.pushUnchecked(bar);
        appended.push(bar);
        continue;
      }
      if (bar.sequence < last.sequence) {
        this.replace(mergeSnapshots(this.toArray(), incoming, this.capacity));
        return {
          appended: [],
          replacedLast: null,
          rebuildRequired: true,
          windowShifted: false
        };
      }
      if (bar.sequence === last.sequence) {
        this.values[this.physicalIndex(this.length - 1)] = bar;
        replacedLast = bar;
        continue;
      }
      this.pushUnchecked(bar);
      appended.push(bar);
    }

    return {
      appended,
      replacedLast,
      rebuildRequired: false,
      windowShifted: firstBefore !== null && this.first?.sequence !== firstBefore
    };
  }

  toArray(): ReplayBar[] {
    const output = new Array<ReplayBar>(this.length);
    for (let index = 0; index < this.length; index += 1) {
      const value = this.values[this.physicalIndex(index)];
      if (value) output[index] = value;
    }
    return output;
  }

  private pushUnchecked(bar: ReplayBar): void {
    if (this.length < this.capacity) {
      this.values[this.physicalIndex(this.length)] = bar;
      this.length += 1;
      return;
    }
    this.values[this.start] = bar;
    this.start = (this.start + 1) % this.capacity;
  }

  private physicalIndex(logicalIndex: number): number {
    return (this.start + logicalIndex) % this.capacity;
  }
}

function normalizeBars(bars: ReplayBar[]): ReplayBar[] {
  if (bars.length < 2) return bars.filter(isValidBar);
  const sorted = bars.filter(isValidBar).sort((left, right) => left.sequence - right.sequence);
  const output: ReplayBar[] = [];
  for (const bar of sorted) {
    const previous = output.at(-1);
    if (previous?.sequence === bar.sequence) output[output.length - 1] = bar;
    else output.push(bar);
  }
  return output;
}

function mergeSnapshots(left: ReplayBar[], right: ReplayBar[], capacity: number): ReplayBar[] {
  const merged = new Map<number, ReplayBar>();
  for (const bar of left) merged.set(bar.sequence, bar);
  for (const bar of right) merged.set(bar.sequence, bar);
  return [...merged.values()]
    .sort((a, b) => a.sequence - b.sequence)
    .slice(-capacity);
}

function isValidBar(bar: ReplayBar): boolean {
  return (
    Number.isFinite(bar.sequence) &&
    Number.isFinite(bar.open_time_ns) &&
    Number.isFinite(Number(bar.open)) &&
    Number.isFinite(Number(bar.high)) &&
    Number.isFinite(Number(bar.low)) &&
    Number.isFinite(Number(bar.close))
  );
}
