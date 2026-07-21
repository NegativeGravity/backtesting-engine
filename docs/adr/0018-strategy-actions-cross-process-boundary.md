# ADR 0018: Strategy Actions Cross the Process Boundary

## Status

Accepted.

## Decision

A strategy process cannot call the broker, data store, persistence layer, or chart vendor directly. Strategy code emits immutable order intents, order-management actions, chart commands, and structured log records. The backtest worker validates and applies those outputs.

## Consequences

- Strategy failures cannot mutate broker state halfway through a callback.
- Broker rules remain authoritative.
- Strategy output can be recorded, replayed, hashed, and audited.
- Live MT5 execution can reuse the same strategy intent boundary with a different executor.
- Every external capability must be exposed deliberately through the SDK.
