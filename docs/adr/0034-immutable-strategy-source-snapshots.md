# ADR 0034: Immutable Strategy Source Snapshots

## Status

Accepted.

## Context

The engine must remain online while external strategy packages are edited or replaced. A live worker may continue executing code already loaded in its isolated process, while deterministic rewind and finalization create new worker processes. Importing the mutable package directory during those operations would allow one run to execute multiple source versions and could invalidate replay determinism.

## Decision

At live-run creation, the engine copies the selected strategy package into `data/live-runs/<run_id>/strategy-source/<package_name>`. Every worker start for that run prepends this snapshot root to its import path. Deterministic rewind and finalization therefore use the same source bytes as the original worker.

The completed replay bundle contains the same package under `data/replay/runs/<run_id>/strategy-source`. The replay manifest records the relative snapshot path and a deterministic SHA-256 tree digest.

## Consequences

- Editing a package affects only runs created after catalog refresh.
- Existing runs remain reproducible through rewind and finalization.
- Strategy packages must be self-contained below their package directory.
- Active live runs still depend on the engine process; completed replay bundles are persistent artifacts.
