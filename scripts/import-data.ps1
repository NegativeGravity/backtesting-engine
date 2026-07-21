$ErrorActionPreference = "Stop"
uv run vex-data import `
  --project-root . `
  --manifest examples\configs\dataset.yaml `
  --symbol-profile examples\configs\symbol_xauusd.yaml `
  --config examples\configs\data_engine.yaml
