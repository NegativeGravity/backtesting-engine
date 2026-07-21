param(
  [int]$MaxCloseBatches = 5000,
  [int]$DashboardPort = 8000,
  [int]$EnginePort = 8001,
  [switch]$ForceRebuild
)
$ErrorActionPreference = "Stop"
$env:VEX_DEMO_MAX_CLOSE_BATCHES = "$MaxCloseBatches"
$env:VEX_DASHBOARD_PORT = "$DashboardPort"
$env:VEX_ENGINE_PORT = "$EnginePort"
$env:VEX_FORCE_REBUILD = $(if ($ForceRebuild) { "1" } else { "0" })
if ($ForceRebuild) {
  docker compose build --no-cache
}
docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
  throw "docker compose up failed"
}
docker compose ps
powershell -ExecutionPolicy ByPass -File .\scripts\docker-smoke.ps1 `
  -DashboardPort $DashboardPort `
  -EnginePort $EnginePort
