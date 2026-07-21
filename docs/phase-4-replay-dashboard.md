# Phase 4 — Replay Dashboard

## Purpose

Phase 4 turns deterministic backtest output into a portable replay product. The dashboard does not execute strategy logic. It reads immutable replay bundles, streams cursor changes through WebSocket, and renders market data, strategy visualizations, broker state, trades, and metrics from the same ordered timeline.

## Deliverables

- Portable SQLite replay bundle
- Versioned replay contracts and JSON Schemas
- Replay catalog and repository
- Deterministic cursor sessions
- REST query API
- WebSocket replay control protocol
- React and TypeScript dashboard
- Lightweight Charts adapter
- Advanced Charts adapter boundary
- Strategy series and drawing renderer
- Trade, order, event, log, account, and performance panels
- Windows setup, build, development, and start scripts

## Architecture

```text
Strategy Backtest Runner
        |
        v
Replay Observer + Output Recorder
        |
        +--------------------------+
        |                          |
        v                          v
Broker Timeline              Strategy Timeline
        |                          |
        +-------------+------------+
                      |
                      v
              Replay Bundle Builder
                      |
                      v
                SQLite Bundle
                      |
          +-----------+------------+
          |                        |
          v                        v
      REST Queries          WebSocket Session
          |                        |
          +-----------+------------+
                      |
                      v
                React Dashboard
                      |
                      v
                   ChartAdapter
                /                \
 Lightweight Charts       Advanced Charts
```

## Replay Bundle

Each run is written under:

```text
data/replay/runs/<run_id>/
```

The bundle contains:

```text
manifest.json
build-result.json
replay.sqlite3
run-config.json
strategy-descriptor.json
strategy-runtime.json
symbol-profiles.json
strategy-report.json
strategy-output/
```

The SQLite database contains:

- Ordered timeline
- Raw timeline staging records
- Broker events
- Account snapshots
- Final order entities
- Fill entities
- Trade entities
- Replay metrics

The bundle is independent of the web process. It can be copied to another machine together with the referenced Parquet dataset and opened without running the strategy again.

## Deterministic Timeline

Timeline ordering is materialized from:

```text
market time
kind priority
source sequence
stable insertion order
```

Kind priority is explicit:

```text
chart command
strategy action
strategy log
broker event
account snapshot
```

A monotonically increasing replay sequence is assigned after sorting. Browser replay uses that sequence instead of wall-clock arrival order.

## Cursor Model

A replay session stores:

```text
run_id
symbol
timeframe
cursor_sequence
cursor_time_ns
playing
speed
```

Supported controls:

```text
play
pause
step_forward
step_backward
seek_time
seek_progress
set_speed
set_timeframe
reset
```

Backward movement and seeking return a full bootstrap state. Forward movement returns a delta frame.

## State Reconstruction

At a requested cursor, the repository reconstructs:

- Visible bars
- Account state
- Orders
- Open positions
- Fills
- Completed trades
- Strategy chart state from chart commands
- Recent events and logs

Terminal order state is shown only after its terminal timestamp. Closed positions are removed after their close event. Trades become visible only after exit.

## Multi-Timeframe Replay

The execution cursor always advances on the run execution timeframe. The selected chart timeframe can be changed independently.

For example:

```text
Execution cursor: M1
Displayed chart: H1
```

When the cursor advances, the API returns only H1 candles whose close time is visible at the current M1 cursor. Future higher-timeframe candles are not exposed.

## Chart Protocol

The strategy chart protocol remains vendor-neutral. Supported commands are:

```text
declare_pane
declare_series
append_series_point
upsert_drawing
delete_drawing
clear_layer
```

Supported drawings are:

```text
trend line
horizontal line
rectangle
marker
label
risk/reward box
```

The frontend materializes chart commands into normalized maps. It does not replay the complete command history on every render. The event table keeps a bounded recent window while the immutable complete timeline remains in SQLite.

## Transport

REST is used for:

- Health
- Run catalog
- Bootstrap
- Historical bar range queries
- Timeline range queries

WebSocket is used for:

- Replay control commands
- Cursor delta frames
- State updates
- Completion notification

Frame rate is separated from backtest throughput. Higher speeds use both shorter send intervals and larger candle batches.

## Dashboard Layout

```text
Top bar
Metrics strip
Replay toolbar
Workspace
  Drawing rail
  Main chart
  State inspector
Bottom dock
  Trades
  Orders
  Events
  Logs
  Performance
Status bar
```

The dashboard supports:

- Run selection
- Multi-timeframe selection
- Play and pause
- Forward and backward candle stepping
- Progress seeking
- Speed control
- Zoom and pan
- Crosshair
- Strategy indicator series
- Strategy drawings
- Trade and order inspection
- Current account state
- Monthly performance matrix

## Performance Boundaries

- Replay database queries are indexed by time and sequence.
- Multi-timeframe close batches use a bounded-memory Arrow k-way merge instead of materializing the complete dataset.
- Strategy output is streamed into the bundle instead of accumulated in a single in-memory payload.
- Browser chart commands are normalized incrementally.
- Browser event history is bounded while the server retains the full timeline.
- Candle deltas are appended instead of replacing the entire chart dataset.
- WebSocket playback batches candles at high speeds.
- Static production assets are served by the API process.

Phase 4 does not yet implement distributed run orchestration, user authentication, server-side chart snapshots for arbitrarily large command histories, or a production deployment topology. Those belong to later product phases.

## Windows Commands

Build a replay bundle:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\replay-build.ps1
```

Run development mode:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\dashboard-dev.ps1
```

Build and run production mode:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\start-dashboard.ps1
```

Open:

```text
http://127.0.0.1:8000
```
