param(
  [string]$ProjectRoot = "G:\PythonProject\backtesting-engine",
  [string]$RunId = ""
)

$ErrorActionPreference = "Stop"
Push-Location $ProjectRoot
try {
  if (-not $RunId) {
    $Run = Get-ChildItem .\data\live-runs -Directory |
      Where-Object Name -Like "run_yj*" |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 1
    if ($null -eq $Run) {
      throw "No YJ live run was found"
    }
    $RunId = $Run.Name
  }

  $RunRoot = Join-Path ".\data\live-runs" $RunId
  $StrategyLogs = Join-Path $RunRoot "strategy-output\strategy-logs.jsonl"
  if (-not (Test-Path $StrategyLogs)) {
    throw "Missing strategy logs: $StrategyLogs"
  }

  $OpenLogs = Get-Content $StrategyLogs |
    ForEach-Object { $_ | ConvertFrom-Json } |
    Where-Object message -eq "yj_position_opened"

  $CloseLogs = Get-Content $StrategyLogs |
    ForEach-Object { $_ | ConvertFrom-Json } |
    Where-Object message -eq "yj_position_closed"

  $MaxConcurrent = 0
  $MissingIdentity = 0
  foreach ($Record in $OpenLogs) {
    $Concurrent = [int]$Record.fields.concurrent_positions
    if ($Concurrent -gt $MaxConcurrent) {
      $MaxConcurrent = $Concurrent
    }
    if (-not $Record.fields.chain_id -or -not $Record.fields.trade_date) {
      $MissingIdentity += 1
    }
  }

  $Bootstrap = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8001/api/runs/$RunId/bootstrap?symbol=XAUUSD&timeframe=M15" `
    -TimeoutSec 30

  $Positions = @($Bootstrap.positions)
  $PositionRows = foreach ($Position in $Positions) {
    [pscustomobject]@{
      PositionId = $Position.position_id
      Side = $Position.side
      TradeDate = $Position.entry_tags.trade_date
      ChainId = $Position.entry_tags.chain_id
      Leg = $Position.entry_tags.leg
      Entry = $Position.average_entry_price_ticks
      Stop = $Position.stop_loss_ticks
      Target = $Position.take_profit_ticks
    }
  }

  [pscustomobject]@{
    RunId = $RunId
    PositionsOpened = @($OpenLogs).Count
    PositionsClosed = @($CloseLogs).Count
    MaximumConcurrentPositionsObserved = $MaxConcurrent
    OpenPositionsNow = $Positions.Count
    OpenLogsMissingChainIdentity = $MissingIdentity
  } | Format-List

  if ($PositionRows.Count -gt 0) {
    $PositionRows | Format-Table -AutoSize
  }

  if ($MissingIdentity -ne 0) {
    throw "Some opened positions do not have authoritative chain/date identity"
  }

  $Catalog = Invoke-RestMethod http://127.0.0.1:8001/api/engine/catalog
  $Strategy = $Catalog.strategies |
    Where-Object package_id -eq "yj_box_breakout" |
    Select-Object -First 1
  if ([string]$Strategy.version -ne "1.3.0") {
    throw "Expected strategy version 1.3.0, found $($Strategy.version)"
  }

  if ($MaxConcurrent -lt 2) {
    Write-Warning "No overlap has occurred in this run yet. Continue the replay until two daily chains overlap."
  }
}
finally {
  Pop-Location
}
