param(
  [int]$DashboardPort = 8000,
  [int]$EnginePort = 8001,
  [int]$TimeoutSeconds = 300
)
$ErrorActionPreference = "Stop"
$DashboardUrl = "http://127.0.0.1:$DashboardPort"
$EngineUrl = "http://127.0.0.1:$EnginePort"
$Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$DashboardHealth = $null
$EngineHealth = $null
while ((Get-Date) -lt $Deadline) {
  try {
    $DashboardHealth = Invoke-RestMethod -Uri "$DashboardUrl/dashboard-health" -TimeoutSec 5
    $EngineHealth = Invoke-RestMethod -Uri "$EngineUrl/api/health" -TimeoutSec 5
    if ($DashboardHealth.status -eq "ok" -and $EngineHealth.status -eq "ok") {
      break
    }
  }
  catch {
    $DashboardHealth = $null
    $EngineHealth = $null
  }
  Start-Sleep -Seconds 2
}
if ($null -eq $DashboardHealth -or $null -eq $EngineHealth) {
  docker compose ps -a
  docker compose logs --tail=200 bootstrap
  docker compose logs --tail=200 engine
  docker compose logs --tail=200 dashboard
  throw "VEX services did not become healthy within $TimeoutSeconds seconds"
}
$Compatibility = Invoke-RestMethod -Uri "$DashboardUrl/api/mt5/compatibility" -TimeoutSec 10
if (-not $Compatibility.compatible) {
  throw "MT5 compatibility endpoint reports a failed validation"
}
$EngineCatalog = Invoke-RestMethod -Uri "$DashboardUrl/api/engine/catalog" -TimeoutSec 10
$Strategy = $EngineCatalog.strategies | Where-Object { $_.package_id -eq "sma_cross_demo" }
if ($null -eq $Strategy) {
  throw "SMA Cross strategy package is missing"
}
$Catalog = Invoke-RestMethod -Uri "$DashboardUrl/api/catalog" -TimeoutSec 10
$Demo = $Catalog.runs | Where-Object { $_.run_id -eq "run_xauusd_sma_cross_demo_v1" }
if ($null -eq $Demo) {
  throw "SMA Cross replay run is missing"
}
$Analytics = Invoke-RestMethod -Uri "$DashboardUrl/api/runs/run_xauusd_sma_cross_demo_v1/analytics" -TimeoutSec 10
if ($Analytics.run_id -ne "run_xauusd_sma_cross_demo_v1") {
  throw "Analytics endpoint returned an unexpected run"
}

$WebSocketUri = [Uri]("ws://127.0.0.1:{0}/api/replay/run_xauusd_sma_cross_demo_v1/ws?symbol=XAUUSD&timeframe=M1" -f $DashboardPort)
$Socket = [System.Net.WebSockets.ClientWebSocket]::new()
$Cancellation = [System.Threading.CancellationTokenSource]::new()
$Cancellation.CancelAfter([TimeSpan]::FromSeconds(30))
$Stream = [System.IO.MemoryStream]::new()
try {
  $Socket.ConnectAsync($WebSocketUri, $Cancellation.Token).GetAwaiter().GetResult()
  if ($Socket.State -ne [System.Net.WebSockets.WebSocketState]::Open) {
    throw "Replay WebSocket did not enter the Open state"
  }
  do {
    $Buffer = New-Object byte[] 65536
    $Segment = [ArraySegment[byte]]::new($Buffer)
    $Result = $Socket.ReceiveAsync($Segment, $Cancellation.Token).GetAwaiter().GetResult()
    if ($Result.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
      throw "Replay WebSocket closed before the bootstrap payload"
    }
    $Stream.Write($Buffer, 0, $Result.Count)
    if ($Stream.Length -gt 16777216) {
      throw "Replay WebSocket bootstrap exceeded 16 MiB"
    }
  } while (-not $Result.EndOfMessage)
  $Text = [System.Text.Encoding]::UTF8.GetString($Stream.ToArray())
  $Message = $Text | ConvertFrom-Json
  if ($Message.type -ne "bootstrap") {
    throw "Replay WebSocket returned an unexpected first message"
  }
  $Socket.CloseAsync(
    [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
    "docker-smoke",
    $Cancellation.Token
  ).GetAwaiter().GetResult()
}
finally {
  $Stream.Dispose()
  $Socket.Dispose()
  $Cancellation.Dispose()
}
[ordered]@{
  dashboard_health = $DashboardHealth.status
  engine_health = $EngineHealth.status
  strategies = $EngineCatalog.strategies.Count
  catalog_runs = $Catalog.runs.Count
  mt5_compatible = $Compatibility.compatible
  demo_run = $Demo.run_id
  analytics_run = $Analytics.run_id
  websocket = "ok"
  dashboard_url = $DashboardUrl
  engine_url = $EngineUrl
} | ConvertTo-Json
