# Running Engine and Dashboard Separately

## Local Windows processes

Open PowerShell window 1:

```powershell
cd G:\PythonProject\backtesting-engine
powershell -ExecutionPolicy ByPass -File .\scripts\start-engine.ps1
```

The engine listens on `http://127.0.0.1:8001`.

Open PowerShell window 2:

```powershell
cd G:\PythonProject\backtesting-engine
powershell -ExecutionPolicy ByPass -File .\scripts\start-dashboard-only.ps1
```

The dashboard listens on `http://127.0.0.1:8000` and proxies API and WebSocket traffic to the engine.

The dashboard can be stopped, rebuilt, or restarted without interrupting a run owned by the engine.

## Docker services

Start data preparation and engine only:

```powershell
docker compose up -d bootstrap engine
```

Start the dashboard later:

```powershell
docker compose up -d dashboard
```

Stop only the dashboard:

```powershell
docker compose stop dashboard
```

Restart only the dashboard:

```powershell
docker compose up -d --force-recreate dashboard
```

Stop the engine only after active runs have been paused, completed, or cancelled:

```powershell
docker compose stop engine
```

## Health checks

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/health
Invoke-RestMethod http://127.0.0.1:8000/dashboard-health
powershell -ExecutionPolicy ByPass -File .\scripts\engine-smoke.ps1
```

## Creating and controlling a run without the dashboard

Create a paused run:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\run-strategy.ps1 `
  -StrategyPackageId sma_cross_demo `
  -RunId run_manual_sma_v1 `
  -MaxCloseBatches 5000
```

Advance one candle batch:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 `
  -RunId run_manual_sma_v1 `
  -Action step_forward `
  -Value 1
```

Play continuously:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 `
  -RunId run_manual_sma_v1 `
  -Action play
```

Pause:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 `
  -RunId run_manual_sma_v1 `
  -Action pause
```

Rewind one candle batch:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 `
  -RunId run_manual_sma_v1 `
  -Action step_backward
```

Reset:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 `
  -RunId run_manual_sma_v1 `
  -Action reset
```

Change speed:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\control-run.ps1 `
  -RunId run_manual_sma_v1 `
  -Action set_speed `
  -Value 50
```

## API equivalents

```text
GET  /api/engine/catalog
POST /api/engine/strategies/refresh
POST /api/engine/runs
GET  /api/engine/runs/{run_id}
POST /api/engine/runs/{run_id}/control
WS   /api/replay/{run_id}/ws
```
