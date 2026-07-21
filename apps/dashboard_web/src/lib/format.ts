export function formatMoney(value: string | number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2
  }).format(Number(value));
}

export function formatNumber(value: string | number, digits = 2): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  }).format(Number(value));
}

export function formatPercent(value: string | number, digits = 2): string {
  return `${formatNumber(value, digits)}%`;
}

export function formatDateTime(timeNs: number): string {
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "UTC"
  }).format(new Date(timeNs / 1_000_000));
}

export function timeNsToSeconds(timeNs: number): number {
  return Math.floor(timeNs / 1_000_000_000);
}

export function signedClass(value: string | number): "positive" | "negative" | "neutral" {
  const numeric = Number(value);
  if (numeric > 0) return "positive";
  if (numeric < 0) return "negative";
  return "neutral";
}
