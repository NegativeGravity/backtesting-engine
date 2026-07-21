# Phase 2 Acceptance Criteria

Phase 2 is accepted when all conditions below pass.

## Orders

- Market, limit, and stop orders follow executable bid and ask sides.
- Orders activate on the next executable bar.
- Gap fills use marketable open rules.
- Limit orders never fill worse than their limit.
- Stop orders apply adverse slippage.
- Expiration, cancellation, modification, duplicate client IDs, and execution rejection are deterministic.

## Positions

- Hedging mode supports independent positions and explicit reduce-only closes.
- Netting mode supports increase, reduction, close, and reversal.
- Partial position closes create trades for the closed volume.
- Protection orders remain synchronized with position volume and levels.
- Every fill references an existing order.

## Accounting

- Commission is deducted at each fill.
- Spread and slippage are attributed separately.
- Balance, equity, floating PnL, margin, free margin, margin level, and drawdown reconcile.
- Margin limits reject unsupported exposure.
- Stop out liquidates deterministically.
- Negative-balance protection is enforced when configured.

## Determinism

- Repeating the same run produces identical IDs, events, trades, snapshots, and report digest.
- Bar sequence regressions are rejected.
- Event sequences are strictly increasing.

## Quality

- Ruff passes.
- Ruff formatting passes.
- Pyright strict mode passes.
- All unit and integration tests pass.
- JSON Schema drift check passes.
- Broker smoke execution succeeds against the Phase 1 Parquet cache.
