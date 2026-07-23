param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [switch]$EnablePackage,

    [switch]$SkipDockerBuild
)

$ErrorActionPreference = "Stop"
$KitRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $ProjectRoot ".backup\ls-volume-delta-v1.0.0-$Timestamp"

$Files = @(
    "strategies/ls_volume_delta/__init__.py",
    "strategies/ls_volume_delta/core.py",
    "strategies/ls_volume_delta/strategy.py",
    "strategies/ls_volume_delta/strategy.yaml",
    "strategies/ls_volume_delta/run.yaml",
    "strategies/ls_volume_delta/runtime.yaml",
    "strategies/ls_volume_delta/package.yaml",
    "strategies/ls_volume_delta/data_engine.yaml",
    "strategies/ls_volume_delta/dataset.template.yaml",
    "strategies/ls_volume_delta/symbol_us30usd.yaml",
    "strategies/ls_volume_delta/README.md",
    "tests/test_ls_volume_delta_core.py",
    "tests/test_ls_volume_delta_contract.py",
    "tests/test_ls_volume_delta_package_static.py"
)

foreach ($RelativePath in $Files) {
    $Source = Join-Path $KitRoot $RelativePath
    $Destination = Join-Path $ProjectRoot $RelativePath

    if (-not (Test-Path $Source)) {
        throw "Missing kit file: $Source"
    }

    if (Test-Path $Destination) {
        $Backup = Join-Path $BackupRoot $RelativePath
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Backup) | Out-Null
        Copy-Item -Force $Destination $Backup
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -Force $Source $Destination
}

$PositionSource = Get-Content `
    (Join-Path $ProjectRoot "src\vex_contracts\positions.py") `
    -Raw
$SimulatorSource = Get-Content `
    (Join-Path $ProjectRoot "src\vex_broker\simulator.py") `
    -Raw

foreach ($Token in @("entry_order_id", "entry_client_order_id", "entry_tags")) {
    if (-not $PositionSource.Contains($Token)) {
        throw "Broker metadata prerequisite missing from positions.py: $Token"
    }
}
foreach ($Token in @(
    "entry_tags=dict(request.tags)",
    "entry_tags=dict(position.entry_tags)"
)) {
    if (-not $SimulatorSource.Contains($Token)) {
        throw "Broker metadata prerequisite missing from simulator.py: $Token"
    }
}

if ($EnablePackage) {
    $DatasetPath = Join-Path $ProjectRoot "strategies\ls_volume_delta\dataset.yaml"
    $ProfilePath = Join-Path $ProjectRoot "strategies\ls_volume_delta\symbol_us30usd.yaml"
    $ImportReport = Join-Path $ProjectRoot "data\cache\us30usd_mt5_ls\1\import-report.json"
    if (-not (Test-Path $DatasetPath)) {
        throw "Create strategies/ls_volume_delta/dataset.template.yaml from dataset.template.yaml first."
    }
    $ProfileText = Get-Content $ProfilePath -Raw
    if ($ProfileText.Contains("replace_with_mt5_compatibility_snapshot")) {
        throw "Replace the placeholder US30USD symbol profile before enabling the package."
    }
    if (-not (Test-Path $ImportReport)) {
        throw "Import report not found: $ImportReport"
    }
    $PackagePath = Join-Path $ProjectRoot "strategies\ls_volume_delta\package.yaml"
    $PackageText = Get-Content $PackagePath -Raw
    $PackageText = $PackageText.Replace("enabled: false", "enabled: true")
    Set-Content -Path $PackagePath -Value $PackageText -Encoding utf8
}

Push-Location $ProjectRoot
try {
    uv run ruff format `
        strategies/ls_volume_delta `
        tests/test_ls_volume_delta_core.py `
        tests/test_ls_volume_delta_contract.py `
        tests/test_ls_volume_delta_package_static.py
    if ($LASTEXITCODE -ne 0) {
        throw "Ruff format failed"
    }

    uv run ruff check `
        strategies/ls_volume_delta `
        tests/test_ls_volume_delta_core.py `
        tests/test_ls_volume_delta_contract.py `
        tests/test_ls_volume_delta_package_static.py
    if ($LASTEXITCODE -ne 0) {
        throw "Ruff check failed"
    }

    uv run pytest -q `
        tests/test_ls_volume_delta_core.py `
        tests/test_ls_volume_delta_contract.py `
        tests/test_ls_volume_delta_package_static.py
    if ($LASTEXITCODE -ne 0) {
        throw "LS strategy tests failed"
    }

    if (-not $SkipDockerBuild) {
        docker compose build
        if ($LASTEXITCODE -ne 0) {
            throw "Docker build failed"
        }
        docker compose up -d --force-recreate
        if ($LASTEXITCODE -ne 0) {
            throw "Docker start failed"
        }
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "LS + Volume Delta strategy v1.0.0 installed."
Write-Host "Backup: $BackupRoot"
Write-Host "Package remains disabled unless -EnablePackage was used."
Write-Host "Do not enable it before creating dataset.template.yaml, importing data, and replacing the placeholder US30USD symbol profile."
