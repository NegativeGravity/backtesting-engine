param(
  [string]$Config = "examples\configs\mt5_bridge.yaml",
  [string]$Output = "data\mt5-compatibility\live-snapshot.json"
)
$ErrorActionPreference = "Stop"
uv run vex-mt5 collect --project-root . --config $Config --output $Output
