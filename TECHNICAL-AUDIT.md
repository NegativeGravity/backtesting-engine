# YJ Parallel Daily Chains and Protection Isolation Audit

## Reference behavior

The uploaded notebook uses one global `Position | None` and gates every initial entry on `position is None`. It is therefore a single-position reference implementation.

Version 1.3.0 preserves the reference logic independently inside each chain and introduces requested cross-day concurrency as an explicit extension.

## Fixed failure modes

### Flat-gated daily entries

Removed `vex.entry.require_flat` and `vex.entry.reevaluate_after_flat` from YJ orders when `allow_overlapping_daily_chains=true`.

### Broker risk limits

The bundled run now uses hedging mode with pyramiding enabled and bounded concurrent-position limits of 512.

### Global reversal association

Removed the strategy-level `_awaiting_reversal` singleton. It could not safely represent multiple chains and was sensitive to broker-event ordering.

### Authoritative position identity

Broker positions and trades now carry:

- original entry order id;
- original entry client order id;
- immutable entry tags.

The strategy resolves `trade_date`, `chain_id`, and `leg` from those tags instead of guessing from event time or the latest available box.

### Reversal isolation

A broker-generated reversal inherits only the source chain's identity tags, receives `leg=2`, and has no further stop-and-reverse instruction. The stop and target are created against the reversal's own `position_id`.

### Balance-based sizing

YJ orders explicitly select `balance` as the sizing basis for initial entries and reversals. This preserves the notebook's realized-balance risk model even when other positions have unrealized PnL.

### Dashboard isolation

Broker drawings remain keyed by `position_id` and `trade_id`. Their payload now contains chain/date/leg identity, and labels display that identity so overlapping rectangles are auditable.

## Invariants covered by focused tests

- Two daily chains can hold positions simultaneously.
- Each open position retains its own stop and target.
- Stopping chain B does not modify chain A protection.
- Chain B reversal inherits B's date and chain id.
- Chain B reversal is leg 2 and cannot generate leg 3.
- Strategy orders in parallel mode contain no flat requirement.
- Initial and reversal sizing use realized balance.

## Validation performed

```text
Python compileall: passed
Focused Python tests: 75 passed
Parallel protection-isolation integration test: passed
TypeScript/TSX syntax parse: 53 files passed
```

A complete npm dependency installation was unavailable in the packaging environment because external package registries returned DNS retry errors. Docker's `npm ci`, `tsc -b`, and Vite build on the target machine remain the final frontend build validation.
