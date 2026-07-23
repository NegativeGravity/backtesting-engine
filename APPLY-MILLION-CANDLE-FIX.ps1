param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$ManifestPath = Join-Path $SourceRoot "MILLION-CANDLE-FILES.txt"

if (-not (Test-Path (Join-Path $ProjectRoot "compose.yaml"))) {
    throw "compose.yaml was not found in $ProjectRoot"
}
if (-not (Test-Path $ManifestPath)) {
    throw "MILLION-CANDLE-FILES.txt was not found beside the installer"
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupRoot = Join-Path $ProjectRoot ".backup\million-candle-v1.5.0-$Timestamp"
New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null

$Files = Get-Content $ManifestPath | Where-Object {
    $_ -and -not $_.StartsWith("#")
}

foreach ($RelativePath in $Files) {
    $Source = Join-Path $SourceRoot $RelativePath
    $Destination = Join-Path $ProjectRoot $RelativePath
    if (-not (Test-Path $Source)) {
        throw "Package file is missing: $RelativePath"
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
    docker compose down --remove-orphans
    if (-not $SkipBuild) {
        docker compose build --no-cache
    }
    docker compose up -d --force-recreate

    $Deadline = (Get-Date).AddMinutes(4)
    $Healthy = $false
    while ((Get-Date) -lt $Deadline) {
        try {
            $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/health" -TimeoutSec 5
            if ($Health.status -eq "ok") {
                $Healthy = $true
                break
            }
        } catch {
        }
        Start-Sleep -Seconds 3
    }
    docker compose ps -a
    if (-not $Healthy) {
        docker compose logs --tail=300 engine
        throw "Engine did not become healthy"
    }
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/api/engine/strategies/refresh" | Out-Null
} finally {
    Pop-Location
}

Write-Host "Vex million-candle engine 1.5.0 installed successfully."
Write-Host "Backup: $BackupRoot"
Write-Host "Dashboard: http://127.0.0.1:8000"
