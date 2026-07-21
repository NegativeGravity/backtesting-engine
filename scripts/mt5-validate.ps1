param(
  [string]$Config = "examples\configs\mt5_validation.yaml",
  [string]$Output = "data\cache\mt5-compatibility-report.json"
)
$ErrorActionPreference = "Stop"
uv run vex-mt5 validate --project-root . --config $Config --output $Output
