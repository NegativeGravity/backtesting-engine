export interface NumericExtent {
  minimum: number;
  maximum: number;
}

export function finiteExtent(values: readonly number[]): NumericExtent | null {
  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;

  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    if (value < minimum) minimum = value;
    if (value > maximum) maximum = value;
  }

  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) return null;
  return { minimum, maximum };
}

export function downsampleEnvelope(values: readonly number[], maxPoints = 1_200): number[] {
  const finiteValues = values.filter(Number.isFinite);
  if (finiteValues.length <= maxPoints || maxPoints < 4) return finiteValues;

  const first = finiteValues.at(0);
  const last = finiteValues.at(-1);
  if (first === undefined || last === undefined) return [];

  const result: number[] = [first];
  const interiorCount = finiteValues.length - 2;
  const targetInterior = maxPoints - 2;
  const bucketCount = Math.max(1, Math.floor(targetInterior / 2));
  const bucketSize = interiorCount / bucketCount;

  for (let bucket = 0; bucket < bucketCount; bucket += 1) {
    const start = 1 + Math.floor(bucket * bucketSize);
    const end = Math.min(finiteValues.length - 1, 1 + Math.floor((bucket + 1) * bucketSize));
    if (start >= end) continue;

    let minIndex = start;
    let maxIndex = start;
    let minValue = finiteValues.at(start);
    let maxValue = finiteValues.at(start);
    if (minValue === undefined || maxValue === undefined) continue;

    for (let index = start + 1; index < end; index += 1) {
      const value = finiteValues.at(index);
      if (value === undefined) continue;
      if (value < minValue) {
        minValue = value;
        minIndex = index;
      }
      if (value > maxValue) {
        maxValue = value;
        maxIndex = index;
      }
    }

    if (minIndex === maxIndex) {
      result.push(minValue);
    } else if (minIndex < maxIndex) {
      result.push(minValue, maxValue);
    } else {
      result.push(maxValue, minValue);
    }
  }

  result.push(last);
  if (result.length <= maxPoints) return result;

  const stride = (result.length - 1) / (maxPoints - 1);
  const compacted: number[] = [];
  for (let index = 0; index < maxPoints; index += 1) {
    const value = result.at(Math.round(index * stride));
    if (value !== undefined) compacted.push(value);
  }
  return compacted;
}
