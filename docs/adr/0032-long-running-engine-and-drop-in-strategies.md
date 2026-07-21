# ADR 0032 — Long-Running Engine and Drop-In Strategies

## Status

Accepted.

## Decision

The backtest engine and dashboard run as independent services. Strategy implementations are loaded from versioned packages mounted under `strategies/`. Every run receives a dedicated spawned strategy process. Catalog refresh affects only future runs.

## Consequences

- Dashboard restarts do not stop engine jobs.
- Strategy source can be replaced without rebuilding the engine image.
- Active runs remain isolated from later package changes.
- The strategy package contract becomes a versioned public boundary.
