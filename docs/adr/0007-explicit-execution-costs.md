# ADR 0007: Explicit Execution Costs

## Status

Accepted

## Decision

Spread, commission, and slippage are explicit run configuration objects. Version 1 supports fixed spread and fixed slippage with configurable commission modes.

## Rationale

Execution costs materially alter strategy results and cannot remain hidden in engine defaults.

## Consequences

- Every run records its cost model.
- Commission currency must match account currency in contract version 1.
- Later broker snapshots can add richer models without changing strategy code.
