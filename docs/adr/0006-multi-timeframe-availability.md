# ADR 0006: Multi-Timeframe Availability

## Status

Accepted

## Decision

Higher-timeframe subscriptions are closed-only by default. Forming-bar access must be requested explicitly.

## Rationale

Implicit access to incomplete or future-completed higher-timeframe candles is a major source of look-ahead bias.

## Consequences

- Availability policy is part of every subscription.
- Execution timeframe must be present in run subscriptions.
- Phase 1 must publish bars according to event time and availability policy.
