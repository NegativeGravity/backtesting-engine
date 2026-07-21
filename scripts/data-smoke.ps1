$ErrorActionPreference = "Stop"
$Report = "data\cache\xauusd_mt5_2025_2026\2\import-report.json"
uv run vex-data query `
  --project-root . `
  --report $Report `
  --symbol XAUUSD `
  --timeframe M15 `
  --limit 5
uv run vex-data sync-preview `
  --project-root . `
  --report $Report `
  --subscription XAUUSD:M1 `
  --subscription XAUUSD:M5 `
  --subscription XAUUSD:H1 `
  --limit 5
