# ADR 0021: Streamed Strategy Output

## Status

Accepted.

## Decision

Strategy actions, chart commands, and logs are written as canonical JSON Lines records through an output recorder. The recorder maintains an incremental SHA-256 digest and can optionally retain outputs in memory for tests.

## Consequences

- Large chart timelines do not require retaining every command in worker memory.
- Replay services can ingest the same chart command stream later.
- Output identity is deterministic and included in the strategy backtest report.
- Output files are append-oriented artifacts rather than mutable strategy state.
