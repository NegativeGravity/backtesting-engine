# ADR 0003: Price, Time, and Money Representation

## Status

Accepted

## Decision

Use integer nanoseconds for engine time, integer ticks for executable prices, decimal average ticks for aggregated fills, and `Decimal` for money and lot sizes.

## Rationale

Binary floating-point values are unsuitable for exact tick alignment, volume steps, commissions, and deterministic equality checks.

## Consequences

- CSV prices are converted using the selected symbol profile.
- UI prices are derived from ticks and tick size.
- Bar duration is validated in nanoseconds.
- Monetary calculations preserve decimal semantics.
