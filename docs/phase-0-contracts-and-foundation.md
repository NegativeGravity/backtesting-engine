# Phase 0: Contracts and Foundation

## Objective

Create a stable and testable boundary between market data, strategies, execution simulation, portfolio accounting, replay, analytics, and the future MT5 bridge before implementing runtime behavior.

## Step 1: Repository Foundation

The repository uses a `src` layout, a single installable contracts package, strict validation, and independent application directories. This keeps Phase 0 simple while preserving future service boundaries.

Outputs:

- `pyproject.toml`
- Python 3.12 baseline
- uv dependency management
- Ruff, Pyright, pytest, and coverage configuration
- CI workflow
- PostgreSQL and Redis local infrastructure

## Step 2: Contract Base

Every contract inherits from one immutable model with the following behavior:

- Extra fields are forbidden.
- Strings are stripped.
- Defaults are validated.
- Mutation after creation is blocked.
- Serialization is explicit and stable.

This prevents silent configuration mistakes and accidental state mutation across process boundaries.

## Step 3: Identity and Versioning

Opaque identifiers are used for runs, strategies, orders, positions, trades, datasets, chart layers, and chart objects. Identifiers are transport-safe and do not encode business state.

Versioning has three independent dimensions:

- Package version
- API version
- Contract schema version

A schema change that breaks readers requires a new contract schema version.

## Step 4: Dataset Manifest

The dataset manifest describes files without reading them. It records:

- Dataset identity and version
- MT5 CSV source
- Repository-relative root
- Bid, ask, or mid price basis
- Source timezone
- Engine timezone
- Symbol and timeframe per file
- Declared and actual ranges
- Row count, file size, checksum, and content hash

The model rejects duplicate symbol-timeframe entries, duplicate paths, path traversal, invalid timezones, and incomplete time ranges.

## Step 5: Symbol Profile

The symbol profile captures broker-dependent instrument behavior:

- Digits and point
- Tick size and tick value
- Contract size
- Volume limits and step
- Profit, margin, and base currencies
- Stop and freeze levels
- Margin fields
- MT5 calculation mode

The profile also provides deterministic price-to-tick conversion and volume normalization.

## Step 6: Run Configuration

A run config completely describes the requested backtest:

- Strategy identity, version, instance, and parameters
- Dataset reference
- Symbol profile references
- Start and end times
- Execution timeframe
- Multi-timeframe subscriptions
- Account settings
- Execution settings
- Risk settings
- Replay settings
- Random seed

The model enforces unique subscriptions, execution timeframe availability, unique profile references, valid dates, and commission currency compatibility.

## Step 7: Account and Execution Settings

Account settings are explicit:

- Initial balance
- Account currency
- Leverage
- Hedging or netting
- Margin-call level
- Stop-out level
- Negative-balance policy

Execution settings are explicit:

- Next-bar-open signal execution
- Next-bar pending-order activation
- Intrabar ambiguity policy
- Gap policy
- Fixed spread
- Fixed commission
- Fixed slippage
- Same-bar exit policy after an open fill

No hidden default may materially alter P&L.

## Step 8: Risk Configuration

Risk supports four sizing contracts:

- Fixed lot
- Risk percent
- Fixed cash risk
- Strategy-defined size

Portfolio limits include total open positions, positions per symbol, pyramiding, allowed directions, and maximum margin usage.

## Step 9: Market and Trading Contracts

The market bar uses integer timestamps and integer price ticks. OHLC consistency and exact timeframe duration are validated.

Trading contracts include:

- Order request
- Order
- Fill
- Modification request
- Cancellation request
- Position
- Closed trade
- Account snapshot

Monetary values and lot sizes use `Decimal`.

## Step 10: Order State Machine

Order transitions are centralized and deterministic.

Allowed lifecycle:

```text
created
  -> accepted
  -> cancelled
  -> rejected

accepted
  -> active
  -> filled
  -> cancelled
  -> expired

active
  -> partially_filled
  -> filled
  -> cancelled
  -> expired

partially_filled
  -> partially_filled
  -> filled
  -> cancelled
  -> expired
```

Filled, cancelled, rejected, and expired are terminal states.

## Step 11: Event Envelope

All runtime components will exchange events through one envelope containing:

- Schema version
- Event ID
- Run ID
- Monotonic sequence
- Event type
- Market event time
- Emission time
- Strategy instance
- Symbol
- Correlation and causation IDs
- Typed payload

Sequence is authoritative for replay ordering. Event time is authoritative for market chronology.

## Step 12: Chart Protocol

Strategies never call TradingView or Lightweight Charts directly. They emit vendor-neutral commands.

Supported chart commands:

- Declare pane
- Declare series
- Append series point
- Upsert drawing
- Delete drawing
- Clear layer

Supported drawings:

- Trend line
- Horizontal line
- Rectangle
- Marker
- Label
- Risk-reward box

Stable object IDs and revisions allow incremental updates during replay.

## Step 13: Canonical Serialization

Contracts can be converted to canonical JSON with stable key ordering and compact separators. SHA-256 fingerprints identify exact validated inputs.

This supports:

- Reproducible runs
- Cache keys
- Artifact identity
- Configuration comparisons
- Audit trails

## Step 14: JSON Schemas

Every public transport contract has an exported JSON Schema. Frontend and service clients can generate compatible types from these schemas in later phases.

## Step 15: Testing

Tests cover:

- Margin-level validation
- Dataset uniqueness and path safety
- Symbol price conversion and volume normalization
- Bar OHLC and duration invariants
- Order lifecycle and terminal behavior
- Dynamic chart command validation
- Run cross-field validation
- Deterministic serialization
- Contract registry and schema export

## Exit Decision

Phase 1 must consume these contracts without modifying their meaning. Additive optional fields are acceptable within schema version 1. Breaking semantic changes require a new schema version and migration plan.
