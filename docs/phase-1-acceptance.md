# Phase 1 Acceptance

## Automated Quality

- Ruff lint passes.
- Ruff format check passes.
- strict Pyright passes for production source.
- all 36 contract and data-engine tests pass.
- all example contracts validate.
- generated JSON Schemas have no drift.
- streaming import stays below 700 MiB peak resident memory for the supplied six-file dataset in the build environment.

## Functional Acceptance

- MT5 M1, M5, M15, H1, H4, and D1 exports are discovered.
- Daily exports without `<TIME>` are accepted with `00:00:00` local open time.
- prices are converted to integer ticks without float conversion.
- timestamps are normalized to UTC nanoseconds.
- duplicate and out-of-order bars are rejected.
- OHLC violations are rejected.
- source metadata is verified against the manifest.
- incomplete trailing bars are marked and excluded from closed-only access.
- Parquet artifacts are checksummed and atomically written.
- repeated imports can reuse matching artifacts.
- M1 aggregation is compared with every higher timeframe.
- closed bars are available through synchronized timestamp batches.
- a failed import still produces a diagnostic report.

## XAUUSD Dataset Verification

The supplied six-file dataset contains 691,893 source bars.

The conservative watermark is `2026-07-13T13:22:00Z`.

One trailing row is marked incomplete in each timeframe.

OHLC aggregation matches exactly across M5, M15, H1, H4, and D1 for all comparable complete intervals.

One H4 tick-volume difference exists at `2026-07-13T08:00:00Z`: source volume `40336`, M1 aggregate `40333`. The OHLC values match. The report records this as a warning rather than altering either source.
