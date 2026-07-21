$ErrorActionPreference = "Stop"
uv run vex-broker smoke `
  --project-root . `
  --run-config examples\configs\run.yaml `
  --symbol-profile examples\configs\symbol_xauusd.yaml `
  --import-report data\cache\xauusd_mt5_2025_2026\2\import-report.json `
  --bars 500 `
  --close-after 120 `
  --output data\cache\broker-smoke-report.json
