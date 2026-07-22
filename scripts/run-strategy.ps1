param(
  [Parameter(Mandatory = $true)]
  [string]$StrategyPackageId,
  [string]$RunId = "",
  [Nullable[int]]$MaxCloseBatches = $null,
  [decimal]$Speed = 10,
  [switch]$Play,
  [string]$EngineUrl = "http://127.0.0.1:8001",
  [string]$ParametersJson = "{}"
)
$ErrorActionPreference = "Stop"
$Parameters = $ParametersJson | ConvertFrom-Json
$Body = [ordered]@{
  strategy_package_id = $StrategyPackageId
  start_paused = -not $Play
  speed_bars_per_second = "$Speed"
  parameters = $Parameters
}
if ($null -ne $MaxCloseBatches) {
  $Body.max_close_batches = $MaxCloseBatches
}
if ($RunId) {
  $Body.run_id = $RunId
}
$Created = Invoke-RestMethod `
  -Method Post `
  -Uri "$EngineUrl/api/engine/runs" `
  -ContentType "application/json" `
  -Body ($Body | ConvertTo-Json -Depth 20)
$Created | ConvertTo-Json -Depth 20
