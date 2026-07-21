param(
  [string]$EngineUrl = "http://127.0.0.1:8001"
)
$ErrorActionPreference = "Stop"
Invoke-RestMethod -Method Post -Uri "$EngineUrl/api/engine/strategies/refresh" | ConvertTo-Json -Depth 20
