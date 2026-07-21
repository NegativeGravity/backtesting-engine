# ADR 0027 — Execution-bar equity curve

## Status

Accepted

## Decision

Persist one compact equity row for every execution bar in the replay SQLite database. Keep replay account snapshots sparse and separate.

## Consequences

Drawdown, exposure and periodic return analytics are independent of replay snapshot frequency. Storage grows linearly with execution bars but remains compact and indexed by timestamp.
