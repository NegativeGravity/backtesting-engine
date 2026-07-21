$ErrorActionPreference = "Stop"
$Dashboard = Join-Path $PSScriptRoot "..\apps\dashboard_web"
if (-not (Test-Path (Join-Path $Dashboard "node_modules"))) {
  & (Join-Path $PSScriptRoot "install-dashboard.ps1")
}
npm run check --prefix $Dashboard
