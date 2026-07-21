# ADR 0029 — Deterministic analytics artifact

## Status

Accepted

## Decision

Materialize a versioned analytics JSON artifact during replay bundle construction. Derive its generation timestamp from the run end time rather than wall-clock time.

## Consequences

Identical runs produce identical analytics identifiers and file hashes. The dashboard can load analytics without rerunning the strategy.
