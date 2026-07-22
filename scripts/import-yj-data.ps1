$ErrorActionPreference = "Stop"
uv run vex-data import `
  --project-root . `
  --manifest strategies\yj_box_breakout\dataset.yaml `
  --symbol-profile strategies\yj_box_breakout\symbol_xauusd_fractional.yaml `
  --config strategies\yj_box_breakout\data_engine.yaml
