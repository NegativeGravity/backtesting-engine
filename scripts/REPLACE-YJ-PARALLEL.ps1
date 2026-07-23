param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"
$SourceRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $ProjectRoot ".backup\yj-parallel-v1.7.1-$Timestamp"

$Files = @(
    "strategies/yj_box_breakout/run.yaml",
    "strategies/yj_box_breakout/strategy.yaml",
    "tests/test_yj_parallel_contract.py",
    "scripts/verify-yj-parallel.py"
)

foreach ($RelativePath in $Files) {
    $SourcePath = Join-Path $SourceRoot $RelativePath
    if (-not (Test-Path $SourcePath)) {
        throw "Replacement file is missing: $SourcePath"
    }

    $DestinationPath = Join-Path $ProjectRoot $RelativePath
    if (Test-Path $DestinationPath) {
        $BackupPath = Join-Path $BackupRoot $RelativePath
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $BackupPath) | Out-Null
        Copy-Item -Force $DestinationPath $BackupPath
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $DestinationPath) | Out-Null
    Copy-Item -Force $SourcePath $DestinationPath
}

Push-Location $ProjectRoot
try {
    uv run ruff format `
        strategies/yj_box_breakout `
        tests/test_yj_parallel_contract.py `
        scripts/verify-yj-parallel.py
    if ($LASTEXITCODE -ne 0) {
        throw "Ruff format failed"
    }

    uv run ruff check `
        strategies/yj_box_breakout `
        tests/test_yj_parallel_contract.py `
        scripts/verify-yj-parallel.py
    if ($LASTEXITCODE -ne 0) {
        throw "Ruff check failed"
    }

    uv run python scripts/verify-yj-parallel.py --project-root .
    if ($LASTEXITCODE -ne 0) {
        throw "YJ parallel verification failed"
    }

    uv run pytest -q `
        tests/test_yj_parallel_contract.py `
        tests/test_yj_strategy.py `
        tests/test_advanced_orders.py
    if ($LASTEXITCODE -ne 0) {
        throw "YJ focused tests failed"
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "YJ parallel daily chains enabled."
Write-Host "Backup: $BackupRoot"
