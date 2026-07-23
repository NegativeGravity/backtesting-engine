param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectRoot = "G:\PythonProject\backtesting-engine"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path

function Assert-LastExitCode {
    param([Parameter(Mandatory = $true)][string]$Message)
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

Push-Location $ProjectRoot
try {
    docker image inspect vex-backtesting-engine:1.5.0 *> $null
    Assert-LastExitCode "Existing image vex-backtesting-engine:1.5.0 was not found."

    $Report = Join-Path $ProjectRoot "data\cache\us30_mt5_ls\1\import-report.json"
    if (-not (Test-Path $Report)) {
        throw "US30 import report is missing: $Report"
    }

    docker compose down --remove-orphans
    Assert-LastExitCode "docker compose down failed."

    docker compose run --rm --no-deps `
        --entrypoint /app/.venv/bin/python `
        engine `
        -c "from pathlib import Path; import importlib, yaml; m=importlib.import_module('strategies.ls_volume_delta.strategy'); p=Path('/app/strategies/ls_volume_delta/package.yaml'); d=yaml.safe_load(p.read_text()); report=(p.parent / d['import_report_path']).resolve(); expected=Path('/app/data/cache/us30_mt5_ls/1/import-report.json').resolve(); assert report == expected, (report, expected); assert report.is_file(), report; assert hasattr(m, 'LsVolumeDeltaStrategy'); assert '_normalized_entry_tags' in Path('/app/strategies/ls_volume_delta/strategy.py').read_text(); print('container_preflight=OK'); print(f'catalog_report={report}')"
    Assert-LastExitCode "Container preflight failed."

    docker compose up -d --force-recreate
    Assert-LastExitCode "Docker startup failed."

    $Deadline = (Get-Date).AddMinutes(4)
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
        Start-Sleep -Seconds 3
    }

    if (-not $Healthy) {
        docker compose ps -a
        docker compose logs --no-color --tail=300 engine
        throw "Engine did not become healthy."
    }

    $Catalog = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8001/api/engine/catalog" `
        -TimeoutSec 20
    $CatalogJson = $Catalog | ConvertTo-Json -Depth 30
    if ($CatalogJson -notmatch "ls_volume_delta") {
        throw "ls_volume_delta is absent from the engine catalog."
    }

    docker compose ps
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Existing Docker image recovered successfully."
Write-Host "Dashboard: http://127.0.0.1:8000"
Write-Host "Create a NEW LS run."
