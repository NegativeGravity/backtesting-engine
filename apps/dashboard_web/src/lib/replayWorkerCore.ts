import type { ReplayBar, ReplayFrame, ReplayTimelineItem } from "./types";

export interface ReplayMergeLimits {
  maxBars: number;
  maxTimelineItems: number;
}

export const DEFAULT_REPLAY_MERGE_LIMITS: ReplayMergeLimits = {
  maxBars: 12_000,
  maxTimelineItems: 20_000
};

export function mergeAdvanceFramesFast(
  left: ReplayFrame,
  right: ReplayFrame,
  limits: ReplayMergeLimits = DEFAULT_REPLAY_MERGE_LIMITS
): ReplayFrame {
  return {
    ...right,
    bars: mergeSortedBars(left.bars, right.bars, limits.maxBars),
    timeline: mergeSortedTimeline(left.timeline, right.timeline, limits.maxTimelineItems),
    account: right.account ?? left.account
  };
}

export function mergeSortedBars(
  left: ReplayBar[],
  right: ReplayBar[],
  maximum: number
): ReplayBar[] {
  if (left.length === 0) return right.slice(-maximum);
  if (right.length === 0) return left.slice(-maximum);

  const output: ReplayBar[] = [];
  let leftIndex = 0;
  let rightIndex = 0;

  while (leftIndex < left.length && rightIndex < right.length) {
    const leftBar = left[leftIndex];
    const rightBar = right[rightIndex];
    if (!leftBar || !rightBar) break;

    const comparison = compareBars(leftBar, rightBar);
    if (comparison < 0) {
      output.push(leftBar);
      leftIndex += 1;
      continue;
    }
    if (comparison > 0) {
      output.push(rightBar);
      rightIndex += 1;
      continue;
    }

    output.push(rightBar);
    leftIndex += 1;
    rightIndex += 1;
  }

  while (leftIndex < left.length) {
    const bar = left[leftIndex];
    if (bar) output.push(bar);
    leftIndex += 1;
  }
  while (rightIndex < right.length) {
    const bar = right[rightIndex];
    if (bar) output.push(bar);
    rightIndex += 1;
  }

  return output.length > maximum ? output.slice(-maximum) : output;
}

export function mergeSortedTimeline(
  left: ReplayTimelineItem[],
  right: ReplayTimelineItem[],
  maximum: number
): ReplayTimelineItem[] {
  if (left.length === 0) return right.slice(-maximum);
  if (right.length === 0) return left.slice(-maximum);

  const output: ReplayTimelineItem[] = [];
  let leftIndex = 0;
  let rightIndex = 0;

  while (leftIndex < left.length && rightIndex < right.length) {
    const leftItem = left[leftIndex];
    const rightItem = right[rightIndex];
    if (!leftItem || !rightItem) break;

    if (leftItem.sequence < rightItem.sequence) {
      output.push(leftItem);
      leftIndex += 1;
      continue;
    }
    if (leftItem.sequence > rightItem.sequence) {
      output.push(rightItem);
      rightIndex += 1;
      continue;
    }

    output.push(rightItem);
    leftIndex += 1;
    rightIndex += 1;
  }

  while (leftIndex < left.length) {
    const item = left[leftIndex];
    if (item) output.push(item);
    leftIndex += 1;
  }
  while (rightIndex < right.length) {
    const item = right[rightIndex];
    if (item) output.push(item);
    rightIndex += 1;
  }

  return output.length > maximum ? output.slice(-maximum) : output;
}

function compareBars(left: ReplayBar, right: ReplayBar): number {
  if (left.symbol !== right.symbol) return left.symbol.localeCompare(right.symbol);
  if (left.timeframe !== right.timeframe) return left.timeframe.localeCompare(right.timeframe);
  if (left.sequence !== right.sequence) return left.sequence - right.sequence;
  return left.open_time_ns - right.open_time_ns;
}
