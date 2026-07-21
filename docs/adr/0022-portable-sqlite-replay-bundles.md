# ADR 0022 — Portable SQLite Replay Bundles

## Status

Accepted

## Context

Replay must remain independent from strategy execution and the dashboard process. It also needs deterministic ordering, efficient point-in-time queries, portability, and low operational overhead during local Windows development.

## Decision

Each completed run is materialized as a versioned directory containing a SQLite database, manifest, configuration snapshots, strategy report, symbol profiles, and raw strategy output.

## Consequences

- A run can be replayed without executing the strategy again.
- The bundle can be copied and audited.
- SQLite provides indexed timeline and entity queries without a database service.
- Large multi-user deployments may later replicate bundle data into an analytical store without changing replay contracts.
