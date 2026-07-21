# ADR 0011: Synchronized Close Batches

## Status

Accepted

## Decision

Bars sharing one close timestamp are emitted as a single batch instead of independent ordered events.

## Consequences

The future strategy runtime can update all timeframe states atomically before callbacks. Event ordering cannot accidentally expose or hide a higher-timeframe close at a shared boundary.
