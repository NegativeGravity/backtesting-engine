param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [switch]$SkipDockerBuild
)

$ErrorActionPreference = "Stop"
$PackageRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $ProjectRoot ".backup\yj-parallel-v1.7.2-$Timestamp"

$Files = @(
    "strategies/yj_box_breakout/strategy.py",
    "strategies/yj_box_breakout/run.yaml",
    "strategies/yj_box_breakout/strategy.yaml",
    "tests/test_yj_parallel_parameter.py"
)

foreach ($RelativePath in $Files) {
    $Source = Join-Path $PackageRoot $RelativePath
    $Destination = Join-Path $ProjectRoot $RelativePath

    if (-not (Test-Path $Source)) {
        throw "Package file not found: $Source"
    }

    if (Test-Path $Destination) {
        $Backup = Join-Path $BackupRoot $RelativePath
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Backup) | Out-Null
        Copy-Item -Force $Destination $Backup
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -Force $Source $Destination
}

Push-Location $ProjectRoot
try {
    uv run ruff format `
        strategies/yj_box_breakout/strategy.py `
        tests/test_yj_parallel_parameter.py

    uv run ruff check `
        strategies/yj_box_breakout/strategy.py `
        tests/test_yj_parallel_parameter.py

    uv run pytest -q `
        tests/test_yj_parallel_parameter.py `
        tests/test_yj_strategy.py `
        tests/test_advanced_orders.py

    if (-not $SkipDockerBuild) {
        docker compose down

        if (Test-Path ".\data\live-runs") {
            Remove-Item ".\data\live-runs\*" -Recurse -Force -ErrorAction SilentlyContinue
        }

        docker compose build --no-cache
        docker compose up -d
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "YJ parallel hotfix v1.7.2 installed."
Write-Host "Backup directory: $BackupRoot"
Write-Host "IMPORTANT: create a NEW backtest run. Existing live-run snapshots still contain the old strategy.py."
