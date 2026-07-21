# ADR 0015: Execution Cost Attribution

## Status

Accepted

## Decision

Actual fill prices include spread and slippage. Execution costs are also calculated explicitly for attribution.

For each completed trade:

- Actual price PnL is calculated from executed entry and exit prices.
- Gross PnL is actual price PnL plus attributed spread and slippage.
- Net PnL is gross PnL minus commission, spread, and slippage plus swap.
- Commission is deducted from account balance at each fill.
- Actual price PnL and swap are credited when a position is closed.

Half of the fixed spread cost is attributed to each fill. A round trip therefore carries one full spread.

## Consequences

- Net PnL equals the account impact without double-counting spread or slippage.
- Dashboard analytics can separate strategy edge from execution costs.
- Open-position equity follows executable close-side prices.
