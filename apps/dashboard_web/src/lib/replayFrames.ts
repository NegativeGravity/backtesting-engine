import type { ReplayBar, ReplayFrame, ReplayTimelineItem } from "./types";

export function mergeAdvanceFrames(left: ReplayFrame, right: ReplayFrame): ReplayFrame {
  return {
    ...right,
    bars: mergeBars(left.bars, right.bars),
    timeline: mergeTimeline(left.timeline, right.timeline),
    account: right.account ?? left.account
  };
}

function mergeBars(left: ReplayBar[], right: ReplayBar[]): ReplayBar[] {
  if (left.length === 0) return right;
  if (right.length === 0) return left;
  const merged = new Map<string, ReplayBar>();
  for (const bar of left) merged.set(barKey(bar), bar);
  for (const bar of right) merged.set(barKey(bar), bar);
  return [...merged.values()].sort((a, b) => a.open_time_ns - b.open_time_ns);
}

function mergeTimeline(
  left: ReplayTimelineItem[],
  right: ReplayTimelineItem[]
): ReplayTimelineItem[] {
  if (left.length === 0) return right;
  if (right.length === 0) return left;
  const merged = new Map<number, ReplayTimelineItem>();
  for (const item of left) merged.set(item.sequence, item);
  for (const item of right) merged.set(item.sequence, item);
  return [...merged.values()].sort((a, b) => a.sequence - b.sequence);
}

function barKey(bar: ReplayBar): string {
  return `${bar.symbol}:${bar.timeframe}:${bar.sequence}`;
}
