# VEX Backtesting Platform

VEX is a deterministic MT5 candle-level backtesting platform with validated multi-timeframe data, an event-driven broker simulator, isolated strategy processes, live candle-by-candle replay, strategy-owned chart output, immutable replay bundles, analytics, and MT5 compatibility validation.

## Final architecture

```text
Validated MT5 data
       |
       v
Backtest Engine :8001
  - strategy package catalog
  - live candle scheduler
  - broker simulator
  - isolated strategy workers
  - replay finalizer
  - analytics and MT5 APIs
       |
       | REST + WebSocket
       v
Dashboard Gateway :8000
  - React application
  - HTTP proxy
  - WebSocket proxy
```

The engine and dashboard are separate services. The engine can remain online while the dashboard is rebuilt or restarted. New strategy packages can be added under `strategies/`, refreshed, and run without restarting the engine.


## Dashboard Pro 1.2

The 1.2 dashboard is a bounded, incremental replay workstation designed for long candle histories and high-speed playback:

- adaptive `smooth`, `balanced`, and `throughput` render profiles
- WebSocket frame coalescing with one React dispatch per render deadline
- incremental candle and strategy-series updates
- fixed 12,000-point browser windows while immutable replay remains on disk
- persistent X/Y scale locks per symbol and timeframe
- resizable inspector and bottom dock
- focus, balanced, and analysis layouts
- fixed timeframe selector: M1, M5, M15, H1, H4, D1
- bounded analytics SVG paths with extrema-preserving downsampling
- opt-in performance diagnostics

See `docs/dashboard-performance-architecture.md` and `docs/VEX-1.2.0-DASHBOARD-PRO-RUNBOOK-FA.md`.

## Core guarantees

- One `step_forward` processes exactly one synchronized closed-candle batch.
- With M1 execution, each step advances one newly closed M1 candle plus any higher-timeframe candles closing at the same timestamp.
- Future bars are never sent to the strategy.
- Closed-only higher-timeframe data remains hidden until its official close.
- Strategy signals, orders, broker fills, feedback, chart commands, and logs complete before the next candle is read.
- The default execution policy fills a signal-created market order no earlier than the next execution-bar open.
- Step-back and seek restart the strategy and broker and deterministically replay to the requested candle.
- Strategy code runs in a separate spawned process.
- Every live run snapshots its strategy package before the first callback; rewind and finalization use that immutable source snapshot.
- Strategy indicators and drawings are emitted through a vendor-neutral chart protocol.
- Completed live runs become immutable SQLite replay and JSON analytics artifacts.

See `docs/architecture/candle-by-candle-execution.md` for the exact event order.

## Requirements

- Windows 10 or Windows 11
- PowerShell
- Python 3.12 managed by `uv`
- Node.js 20.19+ or 22.12+
- Docker Desktop with WSL 2 for container operation
- MetaTrader 5 on the Windows host for live broker validation

## Windows setup

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
winget install OpenJS.NodeJS.LTS
cd G:\PythonProject\backtesting-engine
powershell -ExecutionPolicy ByPass -File .\scripts\setup.ps1
```

PyCharm interpreter:

```text
G:\PythonProject\backtesting-engine\.venv\Scripts\python.exe
```

## Run engine and dashboard separately

PowerShell window 1:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\start-engine.ps1
```

PowerShell window 2:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\start-dashboard-only.ps1
```

Open:

```text
Dashboard  http://127.0.0.1:8000
Engine     http://127.0.0.1:8001
```

Detailed guide: `docs/engine-dashboard-separation.md`.

Persian final runbook: `docs/FINAL-RUNBOOK-FA.md`.

## Docker

Start everything:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-up.ps1
```

Start only bootstrap and engine:

```powershell
docker compose up -d bootstrap engine
```

Start the dashboard later:

```powershell
docker compose up -d dashboard
```

Detailed guide: `docs/docker-final-zero-to-hero.md`.

## Drop-in strategy packages

Enabled strategies live under:

```text
strategies/<package_id>/
```

Create a package by copying:

```text
strategies/_template
```

A package contains:

```text
package.yaml
strategy.yaml
run.yaml
runtime.yaml
strategy.py
__init__.py
```

The engine snapshots each package at run creation. Editing or replacing the package affects only newly created runs. Refresh packages while the engine stays online:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\strategy-refresh.ps1
```

Create a paused candle-by-candle run:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\run-strategy.ps1 `
  -StrategyPackageId sma_cross_demo `
  -RunId run_manual_sma_v1 `
  -MaxCloseBatches 5000
```

Advance exactly one candle batch:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 `
  -RunId run_manual_sma_v1 `
  -Action step_forward `
  -Value 1
```

Continuous play:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 `
  -RunId run_manual_sma_v1 `
  -Action play
```

Full package guide: `docs/external-strategy-packages.md`.

## Included integration strategy

`strategies/sma_cross_demo` provides a complete test strategy with:

- M5 fast and slow SMA signals
- M1 execution
- long and short entries
- stop-loss and take-profit
- opposite-signal position management
- structured logs
- chart series
- signal markers
- risk/reward drawings

It is an integration test strategy, not a profitability claim.

## API

```text
GET  /api/health
GET  /api/catalog
GET  /api/engine/catalog
POST /api/engine/strategies/refresh
POST /api/engine/runs
GET  /api/engine/runs/{run_id}
POST /api/engine/runs/{run_id}/control
GET  /api/runs/{run_id}/bootstrap
GET  /api/runs/{run_id}/analytics
WS   /api/replay/{run_id}/ws
```

## Data preparation

Canonical MT5 CSV files are stored under `data/mt5`. Build the validated Parquet cache:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\import-data.ps1
```

The complete distribution already contains the XAUUSD source data and cache used by the supplied demo.

## MT5 compatibility validation

Offline validation:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\mt5-validate.ps1
```

Live Windows-host collection:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\install-mt5-bridge.ps1
powershell -ExecutionPolicy ByPass -File .\scripts\mt5-collect.ps1
powershell -ExecutionPolicy ByPass -File .\scripts\mt5-validate.ps1
```

Replace the example symbol profile and timezone with values from the target broker before broker-level comparison.

## Quality gate

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\quality.ps1
```

The gate includes:

- Ruff lint and format verification
- strict Pyright
- Python tests
- contract validation
- JSON Schema drift validation
- TypeScript compilation
- frontend tests
- production frontend build
- broker, strategy, replay, and analytics smoke paths when cache data is present

## Repository structure

```text
apps/dashboard_web/              React dashboard
src/vex_contracts/               immutable contracts and schemas
src/vex_data_engine/             MT5 CSV and Parquet data engine
src/vex_broker/                  deterministic broker simulator
src/vex_strategy/                strategy SDK and isolated worker runtime
src/vex_orchestrator/            long-running live backtest engine
src/vex_replay/                  replay bundle and stored replay service
src/vex_analytics/               analytics engine
src/vex_mt5/                     MT5 validation bridge
src/vex_dashboard/               dashboard gateway service
strategies/                      drop-in external strategies
data/live-runs/                  live run working state
data/replay/runs/                completed replay bundles
```

## Fidelity boundary

VEX currently provides deterministic candle-level execution. It does not claim historical tick-path, variable-spread, order-book, queue-priority, market-impact, or partial-liquidity fidelity. Intrabar ambiguity is handled through an explicit configured policy and recorded in the resulting trade data. Active live runs are owned by the engine process; stop or restart the engine only after pausing, cancelling, or completing them. Completed replay bundles remain persistent.

## Final release validation

Release `1.1.0` includes a complete local integration test for the separated engine and dashboard services:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\separated-services-smoke.ps1
```

The smoke test starts the engine and dashboard gateway on independent ports, validates HTTP health, proxies a stored replay WebSocket, creates a new paused live run, advances exactly one candle, completes the run, verifies replay finalization, and checks analytics availability.

The final acceptance report is stored at `FINAL-ACCEPTANCE.json`. The full debug path is:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\full-debug.ps1
```

## Release 1.1.0 chart update

The replay workspace now uses a larger chart-first layout, fixed M1/M5/M15/H1/H4/D1 timeframe controls, animation-frame WebSocket coalescing, incremental candle and indicator updates, persistent horizontal scale settings, persistent price-range locking, and chart focus mode. See `docs/chart-replay-performance.md`.
