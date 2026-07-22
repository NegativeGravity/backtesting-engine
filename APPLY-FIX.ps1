param(
  [string]$ProjectRoot = "G:\PythonProject\backtesting-engine"
)

$ErrorActionPreference = "Stop"
$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $ProjectRoot ".backup\yj-parallel-chains-v4-$Timestamp"

$Files = @(
  "src\vex_broker\advanced_orders.py",
  "src\vex_broker\models.py",
  "src\vex_broker\simulator.py",
  "src\vex_contracts\positions.py",
  "strategies\yj_box_breakout\strategy.py",
  "strategies\yj_box_breakout\run.yaml",
  "strategies\yj_box_breakout\strategy.yaml",
  "strategies\yj_box_breakout\README.md",
  "apps\dashboard_web\src\lib\types.ts",
  "apps\dashboard_web\src\chart\brokerTradeDrawings.ts",
  "apps\dashboard_web\src\chart\drawingPrimitives.ts",
  "apps\dashboard_web\src\chart\brokerTradeDrawings.test.ts",
  "tests\test_advanced_orders.py",
  "tests\test_yj_strategy.py"
)

if (-not (Test-Path $ProjectRoot)) {
  throw "Project root does not exist: $ProjectRoot"
}

foreach ($RelativePath in $Files) {
  $Source = Join-Path $PackageRoot $RelativePath
  if (-not (Test-Path $Source)) {
    throw "Package file is missing: $Source"
  }
}

New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

foreach ($RelativePath in $Files) {
  $Source = Join-Path $PackageRoot $RelativePath
  $Destination = Join-Path $ProjectRoot $RelativePath
  $Backup = Join-Path $BackupRoot $RelativePath

  if (Test-Path $Destination) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Backup) | Out-Null
    Copy-Item -Force $Destination $Backup
  }

  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
  Copy-Item -Force $Source $Destination
}

Push-Location $ProjectRoot
try {
  docker compose down --remove-orphans
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose down failed"
  }

  docker compose build --no-cache
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose build failed"
  }

  docker compose up -d --force-recreate
  if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed"
  }

  $Deadline = (Get-Date).AddMinutes(3)
  $Healthy = $false
  while ((Get-Date) -lt $Deadline) {
    try {
      $Health = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8001/api/health" `
        -TimeoutSec 5
      if ($Health.status -eq "ok") {
        $Healthy = $true
        break
      }
    }
    catch {
    }
    Start-Sleep -Seconds 2
  }

  if (-not $Healthy) {
    docker compose ps -a
    docker compose logs --tail=300 engine
    throw "Engine did not become healthy"
  }

  Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8001/api/engine/strategies/refresh" `
    -TimeoutSec 20 | Out-Null

  $Catalog = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8001/api/engine/catalog" `
    -TimeoutSec 20
  $Strategy = $Catalog.strategies |
    Where-Object package_id -eq "yj_box_breakout" |
    Select-Object -First 1

  if ($null -eq $Strategy) {
    throw "YJ strategy was not found in the engine catalog"
  }
  if ([string]$Strategy.version -ne "1.3.0") {
    throw "Unexpected YJ strategy version: $($Strategy.version)"
  }

  docker compose ps -a
  Write-Host ""
  Write-Host "YJ parallel-chain fix installed successfully."
  Write-Host "Strategy version: 1.3.0"
  Write-Host "Backup: $BackupRoot"
  Write-Host "Create a NEW run. Existing runs keep old strategy and broker snapshots."
  Write-Host "Hard-refresh the dashboard with Ctrl+Shift+R."
}
finally {
  Pop-Location
}
