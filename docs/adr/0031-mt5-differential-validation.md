# ADR 0031 — MT5 Differential Validation

## Status

Accepted

## Decision

Broker compatibility is validated by comparing engine calculations with MT5 terminal outputs captured through `symbol_info`, `account_info`, `order_calc_profit`, and `order_calc_margin`.

Validation never mutates the backtest result and never silently repairs a symbol profile.

## Consequences

- Broker-specific differences are visible before a strategy result is trusted.
- Profit and margin tolerances are explicit and versioned.
- Unsupported MT5 calculation modes fail fast.
- A successful offline fixture validates the framework, while a live broker snapshot is required for broker-specific acceptance.
