# Phase 6 Acceptance

## Completed Gates

- Ruff lint passed
- Ruff formatting passed
- Strict Pyright passed with zero errors
- 109 Python tests passed
- 4 frontend tests passed
- TypeScript compilation passed
- Production frontend build passed
- Contract schema drift check passed
- Offline MT5 compatibility validation passed with 40 checks
- SMA Cross replay built from the real XAUUSD cache
- Replay API health, catalog, bootstrap, and analytics smoke checks passed
- Replay database, analytics report, and strategy report were deterministic across two builds
- Dockerfile, Compose configuration, bootstrap ordering, public registries, and endpoint smoke scripts passed static validation

## Demo Result

- 5000 synchronized close batches
- 4997 execution bars
- 20 completed trades
- 38 strategy actions
- 0 strategy action errors
- 2019 chart commands
- 12389 replay timeline items
- Final balance 99909.5000 USD
- Net PnL -90.5000 USD

The demo strategy is an integration fixture and is not presented as a profitable strategy.

## Defects Found and Corrected

- Strategy order-update parsing now tolerates broker event metadata that is not part of the immutable Order contract.
- Replay catalog tests no longer assume that only one run exists or that catalog ordering is fixed.
- Unsupported MT5 calculation modes are rejected instead of being mapped to an incompatible engine formula.
- Docker startup now waits for health, catalog, and analytics smoke checks before reporting success.
- Public PyPI and npm registries are enforced in lock files, setup scripts, and Docker builds.

## External Gates

The build environment did not provide Docker Engine or a Windows MetaTrader 5 terminal.

Docker assets were statically validated but the final image was not built in this environment.

The offline MT5 fixture validates the compatibility framework, not the user's broker. Broker-specific acceptance requires collecting a live snapshot from the target Windows MT5 terminal and obtaining a report with zero failed checks.
