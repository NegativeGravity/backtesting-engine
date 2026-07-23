param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectRoot = "G:\PythonProject\backtesting-engine",

    [switch]$SkipDockerBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$OriginalPythonPath = $env:PYTHONPATH
$PathSeparator = [System.IO.Path]::PathSeparator

function Assert-LastExitCode {
    param([Parameter(Mandatory = $true)][string]$Message)
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

Push-Location $ProjectRoot
try {
    if ([string]::IsNullOrWhiteSpace($OriginalPythonPath)) {
        $env:PYTHONPATH = $ProjectRoot
    }
    else {
        $env:PYTHONPATH = "$ProjectRoot$PathSeparator$OriginalPythonPath"
    }

    $ImportReport = Join-Path `
        $ProjectRoot `
        "data\cache\us30_mt5_ls\1\import-report.json"
    if (-not (Test-Path $ImportReport)) {
        throw "US30 import report is missing: $ImportReport"
    }

    uv run python `
        .\tools\fix_ls_reverse_metadata.py `
        --project-root . `
        --report .\data\reports\ls-reverse-metadata-v1.0.9.json
    Assert-LastExitCode "LS reverse metadata repair/audit failed."

    $RuffTargets = @(
        ".\src\vex_broker\simulator.py",
        ".\strategies\ls_volume_delta\core.py",
        ".\strategies\ls_volume_delta\strategy.py",
        ".\tools\fix_ls_reverse_metadata.py",
        ".\tests\test_ls_volume_delta_core.py",
        ".\tests\test_ls_reverse_metadata_runtime.py",
        ".\tests\test_ls_reverse_metadata_static.py"
    )

    uv run ruff format @RuffTargets
    Assert-LastExitCode "Ruff format failed."

    uv run ruff check --fix @RuffTargets
    Assert-LastExitCode "Ruff auto-fix failed."

    uv run ruff check @RuffTargets
    Assert-LastExitCode "Ruff validation failed."

    uv run python -m compileall -q `
        .\src\vex_broker\simulator.py `
        .\strategies\ls_volume_delta `
        .\tools\fix_ls_reverse_metadata.py `
        .\tests\test_ls_reverse_metadata_runtime.py
    Assert-LastExitCode "Python compilation failed."

    uv run python -c `
        "import importlib; m=importlib.import_module('strategies.ls_volume_delta.strategy'); assert hasattr(m, 'LsVolumeDeltaStrategy'); print('host_strategy_namespace_import=OK')"
    Assert-LastExitCode "Host strategy namespace import failed."

    uv run python -m pytest -q `
        .\tests\test_ls_volume_delta_core.py `
        .\tests\test_ls_reverse_metadata_runtime.py `
        .\tests\test_ls_reverse_metadata_static.py
    Assert-LastExitCode "LS reverse metadata tests failed."

    if (-not $SkipDockerBuild) {
        docker compose down --remove-orphans
        Assert-LastExitCode "docker compose down failed."

        docker compose build
        Assert-LastExitCode "Docker build failed."

        docker compose run --rm --no-deps `
            --entrypoint /app/.venv/bin/python `
            engine `
            -c "from pathlib import Path; import importlib; m=importlib.import_module('strategies.ls_volume_delta.strategy'); s=Path('/app/strategies/ls_volume_delta/strategy.py').read_text(); c=Path('/app/strategies/ls_volume_delta/core.py').read_text(); b=Path('/app/src/vex_broker/simulator.py').read_text(); assert hasattr(m, 'LsVolumeDeltaStrategy'); assert '_normalized_entry_tags' in s; assert 'resolve_reverse_chain_id' in c; print('container_strategy_recovery=OK'); print('container_broker_position_tags=' + str('position.entry_tags' in b))"
        Assert-LastExitCode "Container reverse metadata preflight failed."

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
    }
}
finally {
    if ($null -eq $OriginalPythonPath) {
        Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $OriginalPythonPath
    }
    Pop-Location
}

Write-Host ""
Write-Host "LS US30 Cover Metadata Hotfix v1.0.9 completed."
Write-Host "Create a NEW run. Do not resume the failed run snapshot."
Write-Host "Dashboard: http://127.0.0.1:8000"
