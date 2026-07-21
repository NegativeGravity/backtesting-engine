param(
  [string]$EngineUrl = "http://127.0.0.1:8001"
)
$ErrorActionPreference = "Stop"
$Health = Invoke-RestMethod -Uri "$EngineUrl/api/health"
$Catalog = Invoke-RestMethod -Uri "$EngineUrl/api/engine/catalog"
if ($Health.status -ne "ok") {
  throw "Engine health check failed"
}
if ($Catalog.strategies.Count -lt 1) {
  throw "No enabled strategy packages were discovered"
}
[ordered]@{
  status = $Health.status
  service = $Health.service
  strategies = $Catalog.strategies.Count
  active_runs = $Catalog.runs.Count
  engine_url = $EngineUrl
} | ConvertTo-Json
