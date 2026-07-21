param(
  [int]$MaxCloseBatches = 5000
)
$ErrorActionPreference = "Stop"
$ImportReport = "data\cache\xauusd_mt5_2025_2026\2\import-report.json"
if (-not (Test-Path $ImportReport)) {
  powershell -ExecutionPolicy ByPass -File .\scripts\import-data.ps1
}
uv run vex-replay build `
  --project-root . `
  --run-config strategies\sma_cross_demo\run.yaml `
  --strategy-descriptor strategies\sma_cross_demo\strategy.yaml `
  --runtime-config strategies\sma_cross_demo\runtime.yaml `
  --symbol-profile examples\configs\symbol_xauusd.yaml `
  --import-report $ImportReport `
  --output-root data\replay\runs `
  --max-close-batches $MaxCloseBatches `
  --snapshot-interval-bars 50 `
  --strategy-source strategies
