# ADR 0016: Position Modes and Protection Orders

## Status

Accepted

## Decision

Both MT5 account modes are supported.

Hedging mode creates independent positions. Opposite orders open independent exposure unless they are explicitly reduce-only and reference a position.

Netting mode maintains at most one position per symbol. Same-side fills increase the position, opposite-side fills reduce it, and excess opposite volume reverses it.

Stop loss and take profit levels are represented as broker-owned reduce-only orders. Protection orders are recreated when position volume or levels change. Filling one protection cancels its sibling.

## Consequences

- Every fill references an existing order.
- Partial position closes preserve auditable protection-order history.
- Position mode behavior is explicit in the run configuration.
