# ADR 0004: Event Envelope and Ordering

## Status

Accepted

## Decision

All runtime events use one versioned envelope. Replay ordering is determined by a monotonic run-local sequence number.

## Rationale

Multiple events can share the same market timestamp. Wall-clock emission order is not a reliable replay order.

## Consequences

- Every event belongs to one run.
- Sequence values cannot move backward.
- Correlation and causation IDs support diagnostics.
- Event payloads can evolve independently through typed contracts.
