# ADR 0012: Broker Timeframes Remain Authoritative

## Status

Accepted

## Decision

Closed higher-timeframe strategy data comes from the broker-exported higher-timeframe file. Lower-timeframe aggregation is used for auditing and forming-bar reconstruction, not silent replacement.

## Consequences

Backtests remain aligned with MT5 chart candles. Cross-timeframe inconsistencies are explicit report findings and can be promoted to import failures through configuration.
