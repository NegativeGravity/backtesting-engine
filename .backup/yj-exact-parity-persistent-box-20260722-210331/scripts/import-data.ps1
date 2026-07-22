$ErrorActionPreference = "Stop"

Write-Host "Importing canonical multi-timeframe dataset..."
uv run vex-data import `
  --project-root . `
  --manifest examples\configs\dataset.yaml `
  --symbol-profile examples\configs\symbol_xauusd.yaml `
  --config examples\configs\data_engine.yaml
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

Write-Host "Importing YJ notebook-parity M15 dataset..."
uv run vex-data import `
  --project-root . `
  --manifest strategies\yj_box_breakout\dataset.yaml `
  --symbol-profile strategies\yj_box_breakout\symbol_xauusd_fractional.yaml `
  --config strategies\yj_box_breakout\data_engine.yaml
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
