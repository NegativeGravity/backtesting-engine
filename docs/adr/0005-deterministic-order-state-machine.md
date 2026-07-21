# ADR 0005: Deterministic Order State Machine

## Status

Accepted

## Decision

Centralize all order status transitions in one deterministic state machine.

## Rationale

Strategies, execution simulation, replay, persistence, and the MT5 bridge must agree on order lifecycle semantics.

## Consequences

- Illegal transitions fail immediately.
- Terminal states cannot reopen.
- Fill application updates volume and average fill price atomically.
- State transitions increment order revision.
