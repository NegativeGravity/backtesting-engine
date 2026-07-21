param(
  [int]$MaxCloseBatches = 5000
)
$ErrorActionPreference = "Stop"
powershell -ExecutionPolicy ByPass -File .\scripts\quality.ps1
powershell -ExecutionPolicy ByPass -File .\scripts\mt5-validate.ps1
powershell -ExecutionPolicy ByPass -File .\scripts\demo-build.ps1 -MaxCloseBatches $MaxCloseBatches
uv run python .\scripts\app_smoke.py
uv run python .\scripts\live_engine_smoke.py
uv run python .\scripts\separated_services_smoke.py
