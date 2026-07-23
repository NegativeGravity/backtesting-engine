param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectRoot = "G:\PythonProject\backtesting-engine"
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

    $StrategyPath = Join-Path `
        $ProjectRoot `
        "strategies\ls_volume_delta\strategy.py"
    if (-not (Test-Path $StrategyPath)) {
        throw "LS strategy file is missing: $StrategyPath"
    }

    uv run ruff format `
        .\strategies\ls_volume_delta\strategy.py `
        .\strategies\ls_volume_delta\core.py `
        .\tests\test_ls_log_fields_contract.py
    Assert-LastExitCode "Ruff format failed."

    uv run ruff check --fix `
        .\strategies\ls_volume_delta\strategy.py `
        .\strategies\ls_volume_delta\core.py `
        .\tests\test_ls_log_fields_contract.py
    Assert-LastExitCode "Ruff auto-fix failed."

    uv run ruff check `
        .\strategies\ls_volume_delta\strategy.py `
        .\strategies\ls_volume_delta\core.py `
        .\tests\test_ls_log_fields_contract.py
    Assert-LastExitCode "Ruff validation failed."

    uv run python -m compileall -q `
        .\strategies\ls_volume_delta `
        .\tests\test_ls_log_fields_contract.py
    Assert-LastExitCode "Python compilation failed."

    uv run python -m pytest -q `
        .\tests\test_ls_log_fields_contract.py `
        .\tests\test_ls_reverse_metadata_runtime.py `
        .\tests\test_ls_reverse_metadata_static.py `
        .\tests\test_ls_volume_delta_core.py
    Assert-LastExitCode "LS log-field and reverse-metadata tests failed."

    uv run python -c `
        "from strategies.ls_volume_delta.strategy import LsVolumeDeltaStrategy; v=LsVolumeDeltaStrategy._log_source_keys({'leg':'2','broker_generated':'stop_and_reverse'}); assert isinstance(v,str); print('scalar_log_fields=OK:',v)"
    Assert-LastExitCode "Scalar log-field smoke test failed."

    docker image inspect vex-backtesting-engine:1.5.0 *> $null
    Assert-LastExitCode `
        "Existing image vex-backtesting-engine:1.5.0 was not found."

    docker compose down --remove-orphans
    Assert-LastExitCode "docker compose down failed."

    docker compose run --rm --no-deps `
        --entrypoint /app/.venv/bin/python `
        engine `
        -c "from strategies.ls_volume_delta.strategy import LsVolumeDeltaStrategy; value=LsVolumeDeltaStrategy._log_source_keys({'broker_generated':'stop_and_reverse','leg':'2'}); assert isinstance(value,str); assert 'source_keys=sorted(raw_tags)' not in open('/app/strategies/ls_volume_delta/strategy.py').read(); print('container_scalar_log_fields=OK:',value)"
    Assert-LastExitCode "Container scalar log-field preflight failed."

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
    if ($null -eq $OriginalPythonPath) {
        Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $OriginalPythonPath
    }
    Pop-Location
}

Write-Host ""
Write-Host "LS US30 Log Fields Hotfix v1.0.11 completed."
Write-Host "Create a NEW run. Do not resume the failed run snapshot."
Write-Host "Dashboard: http://127.0.0.1:8000"
