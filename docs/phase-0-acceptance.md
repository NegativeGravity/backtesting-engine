# Phase 0 Acceptance

## Functional

- Dataset manifests validate MT5 CSV file catalogs.
- Symbol profiles express broker-specific price, volume, contract, and margin fields.
- Run configs express initial balance, leverage, position mode, cost model, risk model, time range, subscriptions, and replay recording.
- Orders, fills, positions, trades, and account snapshots have strict contracts.
- Order lifecycle transitions are centralized.
- Strategy chart output is vendor-neutral.
- Events are versioned and totally ordered within a run.

## Quality

- Contracts are immutable.
- Extra fields are forbidden.
- Canonical serialization is deterministic for identical validated inputs.
- JSON Schemas are generated from source models.
- Positive and negative tests exist for core invariants.
- CI checks linting, formatting, typing, tests, coverage, and schema drift.

## Verification Performed

- Python compilation completed successfully.
- Six example contracts validated successfully.
- Eight public JSON Schemas generated successfully.
- Twenty-six tests passed in the available execution environment.

## Remaining Environment Step

Generate and commit `uv.lock` on a network-enabled Python 3.12 development machine:

```bash
uv lock
uv sync --all-groups
```
