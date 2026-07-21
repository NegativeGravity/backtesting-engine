# ADR 0026 — Bounded-Memory Close-Batch Merge

## Status

Accepted

## Context

Loading every subscribed Parquet series before strategy execution duplicates market data in memory and makes replay bundle generation scale with total dataset size rather than active processing state.

## Decision

`ParquetBarStore.iter_close_batches` streams fixed-size Arrow batches from each subscribed Parquet artifact and performs a deterministic k-way merge by close time, symbol, timeframe, and open time.

## Consequences

- Memory usage is bounded by one Arrow batch per subscribed series and the current close-time group.
- Strategy runs can stop early without loading the remaining dataset.
- Close-batch ordering remains identical to the previous materialized implementation.
- Replay bundle fingerprints remain unchanged for identical inputs.
