param(
  [int]$Port = 8000,
  [int]$EnginePort = 8001,
  [string]$HostAddress = "127.0.0.1",
  [string]$EngineHost = "127.0.0.1",
  [switch]$SkipBuild
)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Dashboard = Join-Path $Root "apps\dashboard_web"
if (-not $SkipBuild) {
  if (-not (Test-Path (Join-Path $Dashboard "node_modules"))) {
    & (Join-Path $PSScriptRoot "install-dashboard.ps1")
  }
  npm run build --prefix $Dashboard
  if ($LASTEXITCODE -ne 0) {
    throw "Dashboard build failed"
  }
}
Set-Location $Root
$EngineUrl = "http://${EngineHost}:$EnginePort"
uv run vex-dashboard --project-root . --engine-url $EngineUrl --host $HostAddress --port $Port
