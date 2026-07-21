$ErrorActionPreference = "Stop"
uv run vex-strategy run `
  --project-root . `
  --run-config examples\configs\run_strategy_smoke.yaml `
  --strategy-descriptor examples\configs\strategy_sdk_smoke.yaml `
  --runtime-config examples\configs\strategy_runtime.yaml `
  --symbol-profile examples\configs\symbol_xauusd.yaml `
  --import-report data\cache\xauusd_mt5_2025_2026\2\import-report.json `
  --max-close-batches 250 `
  --output-directory data\cache\strategy-smoke `
  --report-output data\cache\strategy-smoke-report.json
