param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [switch]$SkipDockerBuild,

    [switch]$SkipDashboardBuild
)

$ErrorActionPreference = "Stop"
$PackageRoot = Split-Path -Parent $PSScriptRoot
$Tool = Join-Path $PackageRoot "tools\apply_vex_yj_parallel_chart_hotfix.py"

if (-not (Test-Path $Tool)) {
    throw "Repair tool not found: $Tool"
}

Push-Location $ProjectRoot
try {
    $Arguments = @(
        "run",
        "python",
        $Tool,
        "--project-root",
        ".",
        "--apply",
        "--verify"
    )
    if ($SkipDashboardBuild) {
        $Arguments += "--skip-dashboard"
    }

    & uv @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "VEX repair or verification failed"
    }

    docker compose down --remove-orphans
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose down failed"
    }

    if (Test-Path ".\data\live-runs") {
        Remove-Item `
            ".\data\live-runs\*" `
            -Recurse `
            -Force `
            -ErrorAction SilentlyContinue
    }

    if (-not $SkipDockerBuild) {
        docker compose build --no-cache
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose build failed"
        }
    }

    docker compose up -d --force-recreate
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed"
    }

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
        throw "Engine did not become healthy"
    }

    try {
        Invoke-RestMethod `
            -Method Post `
            -Uri "http://127.0.0.1:8001/api/engine/strategies/refresh" `
            -TimeoutSec 15 | Out-Null
    }
    catch {
        Write-Warning "Strategy catalog refresh endpoint was not available."
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "YJ metadata + Turbo chart hotfix v1.7.3 installed."
Write-Host "Create a NEW run. Old live-run snapshots contain stale contracts and strategy source."
