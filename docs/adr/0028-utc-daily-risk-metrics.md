# ADR 0028 — UTC daily risk metrics

## Status

Accepted

## Decision

Use canonical UTC end-of-day equity for daily returns, volatility, Sharpe, Sortino, VaR and CVaR.

## Consequences

Results are reproducible across machines and user timezones. Broker-session reporting remains a separate presentation concern.
