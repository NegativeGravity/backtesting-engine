# ADR 0009: Canonical Parquet Bar Schema

## Status

Accepted

## Decision

MT5 CSV files are converted to a fixed canonical schema and stored as Parquet. Prices use integer tradable ticks, timestamps use UTC nanoseconds, and source-row provenance is retained.

## Consequences

Backtest workers avoid CSV parsing and float normalization. Parquet predicate pushdown supports range access. Symbol profiles become part of cache identity because tick conversion depends on broker metadata.
