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
    $PackagePath = Join-Path `
        $ProjectRoot `
        "strategies\ls_volume_delta\package.yaml"
    $ReportPath = Join-Path `
        $ProjectRoot `
        "data\cache\us30_mt5_ls\1\import-report.json"

    if (-not (Test-Path $ReportPath)) {
        throw "US30 import report is missing: $ReportPath"
    }

    uv run python -c `
        "from pathlib import Path; import yaml; p=Path(r'strategies/ls_volume_delta/package.yaml'); d=yaml.safe_load(p.read_text(encoding='utf-8')); d['enabled']=True; d['import_report_path']='../../data/cache/us30_mt5_ls/1/import-report.json'; p.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True), encoding='utf-8'); resolved=(p.parent / d['import_report_path']).resolve(); expected=Path(r'data/cache/us30_mt5_ls/1/import-report.json').resolve(); assert resolved == expected, (resolved, expected); assert resolved.is_file(), resolved; print(f'host_catalog_report={resolved}')"
    Assert-LastExitCode "Could not repair package import_report_path."

    docker compose run --rm --no-deps `
        --entrypoint /app/.venv/bin/python `
        engine `
        -c "from pathlib import Path; import yaml; p=Path('/app/strategies/ls_volume_delta/package.yaml'); d=yaml.safe_load(p.read_text()); resolved=(p.parent / d['import_report_path']).resolve(); expected=Path('/app/data/cache/us30_mt5_ls/1/import-report.json').resolve(); print(f'container_catalog_report={resolved}'); assert resolved == expected, (resolved, expected); assert resolved.is_file(), resolved"
    Assert-LastExitCode "Container cannot resolve the catalog import report."

    docker compose up -d --force-recreate engine dashboard
    Assert-LastExitCode "Engine/dashboard startup failed."

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
Write-Host "LS US30 catalog path hotfix v1.0.7 completed."
Write-Host "Dashboard: http://127.0.0.1:8000"
