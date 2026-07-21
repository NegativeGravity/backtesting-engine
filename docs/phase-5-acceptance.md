# Phase 5 Acceptance

Phase 5 is accepted when all of the following hold:

- every execution bar writes an equity point
- analytics reports validate against the published JSON Schema
- full-run analytics are materialized during replay bundle construction
- point-in-time analytics exclude future trades and equity points
- performance, risk, behavior and execution-cost metrics have unit coverage
- daily, monthly and yearly return series use UTC boundaries
- drawdown episodes are deterministic
- side, symbol, exit reason, weekday and hour breakdowns are available
- P&L, R and duration distributions are generated
- comparison API returns stable rows for selected runs
- Replay and Analytics workspaces are independently navigable
- frontend analytics use no direct broker-state mutation
- Registry URLs remain portable on Windows
- Ruff, Pyright, Pytest, TypeScript, frontend tests and production build pass in the configured development environment
