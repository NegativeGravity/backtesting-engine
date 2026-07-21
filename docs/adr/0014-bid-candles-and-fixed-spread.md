# ADR 0014: Bid Candles and Fixed Spread

## Status

Accepted

## Decision

Phase 2 accepts bid-based MT5 candle data. Ask candles are derived by adding the configured fixed spread after converting spread points to trade ticks.

Execution sides are resolved as follows:

- Buy market orders execute against ask.
- Sell market orders execute against bid.
- Long positions are marked and closed against bid.
- Short positions are marked and closed against ask.
- Buy limits and buy stops trigger against ask.
- Sell limits and sell stops trigger against bid.

A configured spread that is not aligned to the symbol tick size is rejected.

## Consequences

- The simulator remains consistent with the MT5 bid-chart convention.
- Fixed spread can later be replaced by historical bid and ask data behind the same price resolver boundary.
- Mid-price, ask-only, and order-book simulations remain out of scope for Phase 2.
