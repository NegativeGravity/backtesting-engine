# ADR 0013: Deterministic Candle Broker

## Status

Accepted

## Decision

Each backtest run owns one single-threaded broker state machine. Order, fill, position, account, and event IDs are derived from the run identity and monotonic counters. Event timestamps are market timestamps and the event sequence is the canonical replay order.

The broker processes only the configured execution timeframe. Parallelism is applied between independent runs, never inside one mutable broker state.

## Consequences

- Identical inputs produce identical orders, fills, trades, event IDs, and report digests.
- Strategy execution remains isolated from broker accounting.
- Replay can rebuild state from the ordered event stream.
- Higher-level orchestration may execute many broker instances in separate processes.
