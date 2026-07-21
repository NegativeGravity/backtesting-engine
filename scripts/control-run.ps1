param(
  [Parameter(Mandatory = $true)]
  [string]$RunId,
  [Parameter(Mandatory = $true)]
  [ValidateSet("play", "pause", "step_forward", "step_backward", "seek_progress", "reset", "set_speed", "cancel")]
  [string]$Action,
  [string]$Value = "",
  [string]$EngineUrl = "http://127.0.0.1:8001"
)
$ErrorActionPreference = "Stop"
$Body = [ordered]@{ action = $Action }
if ($Value -ne "") {
  $Body.value = $Value
}
Invoke-RestMethod `
  -Method Post `
  -Uri "$EngineUrl/api/engine/runs/$RunId/control" `
  -ContentType "application/json" `
  -Body ($Body | ConvertTo-Json) | ConvertTo-Json -Depth 20
