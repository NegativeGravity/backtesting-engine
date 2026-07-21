$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot
uv run vex-analytics compare `
  --project-root . `
  --run-id run_xauusd_sdk_smoke_v1 `
  --output data\replay\analytics-comparison.json
