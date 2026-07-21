# Final Service Architecture

## Service boundaries

```text
MT5 CSV / Parquet cache
          |
          v
+---------------------------+
| Backtest Engine :8001     |
|                           |
| Strategy Package Catalog  |
| Live Run Orchestrator     |
| Candle Scheduler          |
| Broker Simulator          |
| Strategy Process Host     |
| Replay Finalizer          |
| Analytics API             |
+-------------+-------------+
              |
              | REST + WebSocket
              v
+---------------------------+
| Dashboard Gateway :8000   |
|                           |
| React static application  |
| HTTP reverse proxy        |
| WebSocket reverse proxy   |
+---------------------------+
```

The engine and dashboard are independent processes. Stopping or rebuilding the dashboard does not stop an active backtest. The engine owns data access, strategy execution, broker state, replay state, and final artifacts. The dashboard is a client and gateway only.

## Long-running engine

The engine starts once and discovers enabled strategy packages under `strategies/*/package.yaml`. A new backtest creates a dedicated live job and a dedicated isolated strategy process. The data engine and broker remain implementation details of the engine service.

A strategy source file is not imported into the engine process. The strategy entrypoint is loaded by the spawned worker process. Replacing strategy code and refreshing the catalog is sufficient for subsequent runs; the engine process does not need to restart.

## Live run state

A live run has one of these states:

```text
created -> starting -> paused <-> running
                         |
                         +-> rewinding -> paused
                         |
                         +-> finalizing -> completed
                         |
                         +-> cancelled
                         |
                         +-> failed
```

Completed runs are finalized into immutable replay and analytics artifacts. Active run state is intentionally ephemeral. After an engine restart, completed replay bundles remain available, while unfinished live jobs must be started again.

## Ports

| Service | Default port | Health endpoint |
|---|---:|---|
| Backtest engine | 8001 | `/api/health` |
| Dashboard gateway | 8000 | `/dashboard-health` |

## Storage

```text
data/cache/                         Validated Parquet data and reports
data/live-runs/<run_id>/            Temporary live-run inputs and streamed output
data/replay/runs/<run_id>/          Final immutable replay and analytics bundle
strategies/<package_id>/            Drop-in strategy packages
```


## Run source provenance

The orchestrator snapshots the selected external strategy package before the first callback. The isolated worker, rewind path, and replay finalizer import from that immutable source snapshot. Completed replay manifests include its relative path and SHA-256 tree digest.
