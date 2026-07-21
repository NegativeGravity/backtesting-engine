# ADR 0008: Vendor-Neutral Chart Protocol

## Status

Accepted

## Decision

Strategies emit chart commands instead of calling a chart library directly.

## Rationale

The product may use TradingView Advanced Charts or Lightweight Charts. Strategy logic must remain portable and replayable.

## Consequences

- Chart objects use stable IDs and revisions.
- Drawings belong to layers.
- Dashboard adapters translate commands into vendor-specific operations.
- Recorded chart commands can be replayed without re-running the strategy.
