# ADR 0017: Margin Call and Stop Out

## Status

Accepted

## Decision

Required margin is calculated from the symbol calculation mode, contract size, current executable price, volume, configured leverage, and optional fixed initial margin.

Orders that would exceed free margin or the configured maximum margin-usage percentage are rejected at execution.

At each execution-bar close the broker recalculates balance, equity, floating PnL, margin, free margin, margin level, peak equity, and drawdown. Margin-call and stop-out events are emitted when configured thresholds are crossed.

Stop-out liquidation closes the worst unrealized position first until margin level recovers or no positions remain. When negative balance is disabled, an account with no positions is floored at zero.

## Consequences

- Candle-level liquidation is deterministic but cannot reconstruct tick-level liquidation timing.
- Stop-out behavior is conservative and visible in the event log.
- Multi-currency conversion remains outside Phase 2 and is rejected by configuration validation.
