# Contributing

## Rules

- Production code is English-only.
- Inline comments are not used.
- Public behavior is documented in contracts and ADRs.
- Unknown configuration fields are rejected.
- Domain models remain immutable.
- Business rules require tests.
- Service implementations depend on contracts, not on another service implementation.
- Breaking contract changes require a schema version change and migration plan.
- Monetary values and lot sizes use `Decimal`.
- Executable prices use ticks.
- Engine time uses integer nanoseconds.
- Strategy code depends on `vex_strategy` and contracts, not broker or data implementations.
- Strategy entrypoints remain importable under the Windows `spawn` process model.
- Strategy output is emitted through actions, chart commands, and structured logs.
- Replay ordering is defined by the server timeline, never browser arrival time.
- Chart implementations depend on `ChartAdapter` and vendor-neutral chart contracts.
- Licensed chart assets are never committed or redistributed.
- The browser retains bounded operational history while immutable full history remains server-side.

## Before Commit

```bash
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pyright
uv run pytest
uv run vex-contracts export-schemas --output schemas
uv run python scripts/check_schema_drift.py
npm run check --prefix apps/dashboard_web
```

## Contract Change Process

1. Add or update the contract model.
2. Add cross-field validation.
3. Add positive and negative tests.
4. Regenerate JSON Schemas.
5. Update the relevant contract document.
6. Add an ADR for semantic changes.
7. Determine whether the change is additive or breaking.
