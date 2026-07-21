# Phase 4 Acceptance Criteria

## Replay Bundle

- [x] A run can be converted into a portable replay bundle.
- [x] Broker events and strategy output share one deterministic timeline.
- [x] Account snapshots are persisted.
- [x] Orders, fills, and trades are persisted as queryable entities.
- [x] Replay metrics are persisted.
- [x] Maximum drawdown is tracked across all execution bars.
- [x] The bundle has a versioned manifest and SHA-256 database fingerprint.

## Repository and API

- [x] Run bundles are discovered through a catalog.
- [x] Bootstrap reconstructs state at a cursor.
- [x] Historical bars are queried from Parquet.
- [x] Timeline ranges are queried from SQLite.
- [x] Multi-timeframe visibility follows the execution cursor.
- [x] Play, pause, step, seek, speed, timeframe, and reset controls are supported.
- [x] WebSocket sessions emit deterministic delta frames.
- [x] Missing runs return explicit errors.
- [x] Production frontend assets can be served by the API.

## Dashboard

- [x] The application is implemented in React and TypeScript.
- [x] The main chart supports candlesticks, zoom, pan, crosshair, and future space.
- [x] Strategy line series are rendered.
- [x] Trend lines, levels, rectangles, markers, labels, and risk/reward boxes are rendered.
- [x] Run and timeframe selectors are available.
- [x] Replay controls are available.
- [x] Account metrics update with the cursor.
- [x] Trade, order, event, log, and performance panels are available.
- [x] A monthly result matrix is available.
- [x] The client incrementally materializes chart state.
- [x] The visible event window is bounded.
- [x] A chart vendor adapter boundary exists.

## Engineering Quality

- [x] Python code passes Ruff.
- [x] Python code passes strict Pyright.
- [x] Python tests pass.
- [x] TypeScript compilation passes.
- [x] Frontend tests pass.
- [x] Production frontend build passes.
- [x] JSON Schemas are generated without drift.
- [x] Windows PowerShell setup and run scripts are included.
- [x] CI covers Python and frontend quality on Windows and Linux.
