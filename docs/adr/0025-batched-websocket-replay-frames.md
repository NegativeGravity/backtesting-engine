# ADR 0025 — Batched WebSocket Replay Frames

## Status

Accepted

## Context

Sending every candle and event as an individual message creates unnecessary serialization, rendering, and scheduling overhead at high replay speeds.

## Decision

The replay session emits cursor frames containing one or more execution bars, all visible chart bars for the selected timeframe, timeline deltas, and the latest account state. Batch size increases with replay speed.

## Consequences

- High-speed replay remains responsive.
- UI update frequency is decoupled from candle count.
- Every frame preserves ordered deltas.
- The browser performs fewer state transitions and chart updates.
