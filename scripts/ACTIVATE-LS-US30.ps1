param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectRoot = "G:\PythonProject\backtesting-engine",

    [switch]$SkipDockerBuild,

    [switch]$ForceDataImport
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path

function Assert-LastExitCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

Push-Location $ProjectRoot
try {
    $ImportReport = Join-Path `
        $ProjectRoot `
        "data\cache\us30_mt5_ls\1\import-report.json"

    if ($ForceDataImport -or -not (Test-Path $ImportReport)) {
        uv run python `
            .\tools\prepare_us30_ls.py `
            --project-root . `
            --source-timezone Asia/Tehran `
            --enable
        Assert-LastExitCode "US30 dataset preparation/import failed."
    }
    else {
        uv run python -c `
            "from pathlib import Path; import yaml; p=Path(r'strategies/ls_volume_delta/package.yaml'); d=yaml.safe_load(p.read_text(encoding='utf-8')); d['enabled']=True; d['import_report_path']='../../data/cache/us30_mt5_ls/1/import-report.json'; p.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True), encoding='utf-8'); resolved=(p.parent / d['import_report_path']).resolve(); expected=Path(r'data/cache/us30_mt5_ls/1/import-report.json').resolve(); assert resolved == expected, (resolved, expected); assert resolved.is_file(), resolved; print(f'Catalog import report path: {resolved}')"
        Assert-LastExitCode "Could not preserve package enabled state."
        Write-Host "Using existing successful US30 import report."
    }

    uv run python `
        .\tools\audit_ls_broker_metadata.py `
        --project-root . `
        --repair `
        --report .\data\reports\ls-broker-metadata-audit.json
    Assert-LastExitCode "Broker metadata audit/repair failed."

    $RuffTargets = @(
        ".\strategies\ls_volume_delta",
        ".\tools\prepare_us30_ls.py",
        ".\tools\audit_ls_broker_metadata.py",
        ".\tests\test_ls_volume_delta_core.py",
        ".\tests\test_ls_volume_delta_contract.py",
        ".\tests\test_ls_volume_delta_package_static.py"
    )

    uv run ruff format @RuffTargets
    Assert-LastExitCode "Ruff format failed."

    uv run ruff check --fix @RuffTargets
    Assert-LastExitCode "Ruff auto-fix failed."

    uv run ruff check @RuffTargets
    Assert-LastExitCode "Ruff validation failed."

    uv run python -m compileall -q `
        .\strategies\ls_volume_delta `
        .\tools\prepare_us30_ls.py `
        .\tools\audit_ls_broker_metadata.py
    Assert-LastExitCode "Python compilation failed."

    uv run pytest -q `
        .\tests\test_ls_volume_delta_core.py `
        .\tests\test_ls_volume_delta_contract.py `
        .\tests\test_ls_volume_delta_package_static.py
    Assert-LastExitCode "LS Volume Delta tests failed."

    uv run python -c `
        "from strategies.ls_volume_delta.strategy import LsVolumeDeltaParameters; p=LsVolumeDeltaParameters(); assert p.symbol == 'US30'; assert str(p.primary_reward_risk) == '2'; print('LS strategy import: OK')"
    Assert-LastExitCode "LS strategy import smoke test failed."

    if (-not $SkipDockerBuild) {
        docker compose down --remove-orphans
        Assert-LastExitCode "docker compose down failed."

        if (Test-Path ".\data\live-runs") {
            Remove-Item `
                ".\data\live-runs\*" `
                -Recurse `
                -Force `
                -ErrorAction SilentlyContinue
        }

        docker compose build
        Assert-LastExitCode "Docker build failed."

        docker compose run --rm --no-deps `
            --entrypoint /app/.venv/bin/python `
            engine `
            -c "from pathlib import Path; import yaml; p=Path('/app/strategies/ls_volume_delta/package.yaml'); d=yaml.safe_load(p.read_text()); resolved=(p.parent / d['import_report_path']).resolve(); expected=Path('/app/data/cache/us30_mt5_ls/1/import-report.json').resolve(); print(f'container_catalog_report={resolved}'); assert resolved == expected, (resolved, expected); assert resolved.is_file(), resolved"
        Assert-LastExitCode "Container catalog path preflight failed."

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
            docker compose logs --tail=300 engine
            throw "Engine did not become healthy."
        }

        docker compose exec -T engine `
            /app/.venv/bin/python `
            -c "from vex_contracts.positions import Position, Trade; from strategies.ls_volume_delta.strategy import LsVolumeDeltaParameters; required={'entry_order_id','entry_client_order_id','entry_tags'}; assert required <= set(Position.model_fields); assert required <= set(Trade.model_fields); assert LsVolumeDeltaParameters().symbol == 'US30'; print('container contract smoke: OK')"
        Assert-LastExitCode "Container contract smoke test failed."

        try {
            Invoke-RestMethod `
                -Method Post `
                -Uri "http://127.0.0.1:8001/api/engine/strategies/refresh" `
                -TimeoutSec 15 | Out-Null
        }
        catch {
        }

        $Catalog = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8001/api/engine/catalog" `
            -TimeoutSec 20
        $CatalogJson = $Catalog | ConvertTo-Json -Depth 30
        if ($CatalogJson -notmatch "ls_volume_delta") {
            throw "ls_volume_delta is absent from the engine catalog."
        }
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "LS + 2m Volume Delta US30 catalog path hotfix v1.0.7 completed."
Write-Host "Audit report: data\reports\ls-broker-metadata-audit.json"
Write-Host "Dashboard: http://127.0.0.1:8000"
Write-Host "Create a NEW run using package: ls_volume_delta"
