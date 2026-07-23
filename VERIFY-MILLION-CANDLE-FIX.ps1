param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [string]$RunId = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
Push-Location $ProjectRoot
try {
    docker compose ps -a
    $Engine = Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/health" -TimeoutSec 10
    $Dashboard = Invoke-RestMethod -Uri "http://127.0.0.1:8000/dashboard-health" -TimeoutSec 10
    Write-Host "Engine:" ($Engine | ConvertTo-Json -Compress)
    Write-Host "Dashboard:" ($Dashboard | ConvertTo-Json -Compress)

    $Catalog = Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/engine/catalog" -TimeoutSec 20
    $Catalog.strategies | Select-Object package_id, name, version, enabled | Format-Table

    if ($RunId) {
        $State = Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/engine/runs/$RunId" -TimeoutSec 20
        $State | Select-Object run_id, status, visualization_mode, speed_bars_per_second,
            processed_close_batches, processed_execution_bars, progress, replay_ready, error |
            Format-List
    }

    docker stats --no-stream
} finally {
    Pop-Location
}
