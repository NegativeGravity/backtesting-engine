$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "normalize-registry-locks.ps1")
uv run ruff check src tests scripts strategies
uv run ruff format --check src tests scripts strategies
uv run pyright
uv run pytest
uv run vex-contracts validate --kind dataset-manifest --path examples\configs\dataset.yaml
uv run vex-contracts validate --kind data-engine-config --path examples\configs\data_engine.yaml
uv run vex-contracts validate --kind symbol-profile --path examples\configs\symbol_xauusd.yaml
uv run vex-contracts validate --kind strategy-descriptor --path examples\configs\strategy.yaml
uv run vex-contracts validate --kind run-config --path examples\configs\run.yaml
uv run vex-contracts validate --kind strategy-runtime-config --path examples\configs\strategy_runtime.yaml
uv run vex-contracts validate --kind analytics-config --path examples\configs\analytics.yaml
uv run vex-contracts validate --kind strategy-descriptor --path examples\configs\strategy_sdk_smoke.yaml
uv run vex-contracts validate --kind run-config --path examples\configs\run_strategy_smoke.yaml
uv run vex-contracts validate --kind mt5-bridge-config --path examples\configs\mt5_bridge.yaml
uv run vex-contracts validate --kind mt5-validation-config --path examples\configs\mt5_validation.yaml
uv run vex-contracts validate --kind mt5-compatibility-snapshot --path examples\mt5\xauusd_offline_snapshot.json
uv run vex-contracts validate --kind strategy-package-manifest --path strategies\sma_cross_demo\package.yaml
uv run vex-contracts validate --kind strategy-descriptor --path examples\configs\strategy_sma_cross.yaml
uv run vex-contracts validate --kind run-config --path examples\configs\run_sma_cross.yaml
uv run python scripts\check_schema_drift.py
$Dashboard = Join-Path $PSScriptRoot "..\apps\dashboard_web"
if (-not (Test-Path (Join-Path $Dashboard "node_modules"))) {
  & (Join-Path $PSScriptRoot "install-dashboard.ps1")
}
npm run check --prefix $Dashboard
$Report = "data\cache\xauusd_mt5_2025_2026\2\import-report.json"
if (Test-Path $Report) {
  powershell -ExecutionPolicy ByPass -File .\scripts\broker-smoke.ps1 | Out-Null
  powershell -ExecutionPolicy ByPass -File .\scripts\strategy-smoke.ps1 | Out-Null
  powershell -ExecutionPolicy ByPass -File .\scripts\replay-build.ps1 | Out-Null
  powershell -ExecutionPolicy ByPass -File .\scripts\analytics-report.ps1 | Out-Null
  uv run python .\scripts\app_smoke.py | Out-Null
  uv run python .\scripts\live_engine_smoke.py | Out-Null
}
