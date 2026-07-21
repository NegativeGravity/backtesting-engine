# ADR 0001: Repository and Service Boundaries

## Status

Accepted

## Decision

Use one repository with independent application directories and one shared contracts package during the initial phases.

## Applications

- Backtest API
- Backtest Worker
- Dashboard Web
- Future MT5 Bridge

## Rationale

The contracts must evolve atomically while the runtime services are still being built. Independent deployables remain possible without introducing package publishing and distributed version coordination during Phase 0.

## Consequences

- Contracts are shared by source during development.
- Applications cannot import each other's implementation modules.
- Service-specific logic must not be added to `vex_contracts`.
- The contracts package can be published independently when deployment boundaries require it.
