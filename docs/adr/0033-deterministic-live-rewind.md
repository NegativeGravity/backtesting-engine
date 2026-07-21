# ADR 0033 — Deterministic Live Rewind

## Status

Accepted.

## Decision

Step-back, reset, and seek reconstruct strategy and broker state by restarting the isolated worker and replaying closed-bar batches from the original run inputs.

## Consequences

- Rewind matches a clean run to the same candle.
- Indicator state, drawings, orders, positions, and account state cannot diverge through partial rollback.
- Rewind cost grows with cursor distance until checkpoint support is introduced.
