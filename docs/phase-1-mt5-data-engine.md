# Phase 1 — MT5 Data Engine

## Scope

Phase 1 converts versioned MT5 CSV exports into validated, deterministic, queryable, multi-timeframe Parquet datasets. It does not implement order execution, portfolio accounting, or strategy logic.

## Pipeline

```text
Dataset Manifest
    |
    v
Path Resolution
    |
    v
Filename and Schema Validation
    |
    v
Bounded-Memory String Parsing
    |
    v
Timezone Localization
    |
    v
Exact Price-to-Tick Conversion
    |
    v
Market Data Validation
    |
    v
Completion Watermark
    |
    v
Atomic Parquet Cache
    |
    +--------------------+
    |                    |
    v                    v
Resolved Manifest    Cross-Timeframe Audit
    |                    |
    +----------+---------+
               |
               v
         Import Report
```

## Source Resolution

The manifest remains authoritative. The engine first tries each declared relative path. When a path is missing, deterministic discovery matches one file by `symbol + timeframe`. This allows Windows duplicate suffixes and the `Daily` alias without weakening duplicate detection.

Accepted examples:

```text
XAUUSD_M1_202501020105_202607131322.csv
XAUUSD_M1_202501020105_202607131322(1).csv
XAUUSD_Daily_202501020000_202607130000(2).csv
XAUUSD_D1_202501020000_202607130000.csv
```

## Parsing Policy

Every source field is parsed from its original text representation. The engine never relies on CSV schema inference for prices or timestamps. Parsing is performed in configurable row batches and emitted directly as Arrow record batches, so the full CSV is never retained in memory during cache creation.

Price conversion is exact:

```text
price text
    -> fixed-scale decimal
    -> integer point units
    -> divisibility check against trade_tick_size
    -> integer tradable ticks
```

No binary floating-point value participates in price normalization.

## Canonical Bar Schema

| Column | Type | Meaning |
|---|---|---|
| `symbol` | string | MT5 symbol |
| `timeframe` | string | canonical timeframe |
| `open_time_ns` | int64 | UTC bar open time |
| `close_time_ns` | int64 | UTC bar close time |
| `open_ticks` | int64 | open in tradable ticks |
| `high_ticks` | int64 | high in tradable ticks |
| `low_ticks` | int64 | low in tradable ticks |
| `close_ticks` | int64 | close in tradable ticks |
| `tick_volume` | int64 | MT5 tick volume |
| `real_volume` | int64 | MT5 real volume |
| `source_spread_points` | int32 | spread exported by MT5 |
| `sequence` | int64 | deterministic row sequence |
| `source_row` | int64 | original CSV line number |
| `is_complete` | bool | bar is closed at the import watermark |

## Completion Watermark

When `as_of_time` is configured, it is the explicit completion watermark.

When it is absent, the engine selects the smallest fixed-duration timeframe and reads its final bar-open timestamp. For multiple symbols, it uses the earliest per-symbol watermark. A bar is complete only when:

```text
bar.close_time <= completion_watermark
```

The default `mark_incomplete` policy retains trailing snapshots but prevents them from appearing in closed-only queries and synchronized close batches.

## Validation

Errors prevent a successful import:

- source hash mismatch
- source size mismatch
- source row-count mismatch
- declared start or end mismatch
- timestamp parse failure
- numeric parse failure
- non-aligned price
- negative volume or spread
- OHLC invariant failure
- duplicate timestamps
- out-of-order timestamps
- rejected trailing incomplete bars

Informational findings are retained in the report:

- expected market-time gaps
- retained trailing incomplete bars

Cross-timeframe differences are warnings. They can make the import fail when `fail_on_warnings` is enabled.

## Gap Semantics

The data engine measures timestamp gaps but does not synthesize bars. Weekends, broker maintenance, daily breaks, and missing market data cannot be distinguished without an explicit trading-session calendar. Gap metrics are therefore diagnostic, not automatic errors.

## Cross-Timeframe Audit

The configured base timeframe is assigned to each source higher-timeframe interval. The engine aggregates:

```text
open = first lower-timeframe open
high = maximum lower-timeframe high
low = minimum lower-timeframe low
close = last lower-timeframe close
tick_volume = sum lower-timeframe tick volume
```

Only complete intervals fully inside base-timeframe coverage are compared. OHLC differences use `price_tolerance_ticks`. Tick-volume comparison can be disabled independently.

Source higher-timeframe bars remain authoritative for closed-bar strategy access. The audit exposes inconsistencies without silently replacing broker candles.

## Cache Semantics

A cache key includes:

- source SHA-256
- symbol profile
- trailing-bar policy
- explicit as-of time
- inferred completion watermark
- Parquet compression settings
- row-group size
- CSV batch size
- canonical cache schema version

Parquet and metadata files are written to temporary files in the target directory and atomically replaced. Every artifact stores both source and output SHA-256 values.

## Query Semantics

`ParquetBarStore` uses lazy Parquet scans with predicate pushdown for symbol/timeframe ranges. Closed-only queries filter `is_complete` before collection.

Available operations:

- range load
- latest closed bar
- closed-bar window
- synchronized close batches
- lower-timeframe forming-bar aggregation

## Multi-Timeframe Synchronization

All bars sharing a close timestamp are grouped into one `BarCloseBatch`. A future strategy runtime must apply the entire batch to market state before invoking strategy code. This avoids arbitrary callback ordering at boundaries such as an M1, M5, M15, and H1 close occurring at the same instant.

## Output Layout

```text
data/cache/<dataset_id>/<dataset_version>/
  dataset.resolved.yaml
  import-report.json
  <symbol>/
    M1.parquet
    M1.meta.json
    M5.parquet
    M5.meta.json
```

## Failure Behavior

The engine writes an import report even when validation fails. Invalid source files do not receive new cache artifacts. No malformed row is silently repaired, reordered into success, or synthesized.

## Performance Characteristics

The importer uses bounded-memory CSV batches and a streaming Parquet writer. Cross-timeframe validation loads higher-timeframe bars once and streams the M1 base once for all target timeframes.

Measured in the build environment for the supplied 691,893-row dataset:

```text
full import and five cross-timeframe audits: 23.71 seconds
peak resident memory: 653,196 KiB
import without cross-timeframe audit: 17.31 seconds
peak resident memory without audit: 452,828 KiB
```

These figures are environment-specific and are recorded as engineering measurements, not fixed product guarantees.
