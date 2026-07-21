$ErrorActionPreference = "Stop"

$ProjectRoot = (Get-Location).Path
$ComposePath = Join-Path $ProjectRoot "compose.yaml"
$OverridePath = Join-Path $ProjectRoot "compose.override.yaml"

if (-not (Test-Path $ComposePath)) {
    throw "compose.yaml was not found in $ProjectRoot"
}

if (Test-Path $OverridePath) {
    $Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Copy-Item $OverridePath "$OverridePath.backup-$Timestamp"
}

$Override = @'
services:
  app:
    command:
      - python
      - -c
      - "from vex_replay.api import main; raise SystemExit(main())"
      - --project-root
      - /app
      - --host
      - 0.0.0.0
      - --port
      - "8000"
'@

[System.IO.File]::WriteAllText(
    $OverridePath,
    $Override,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "Created compose.override.yaml with a deterministic API entrypoint."

$Resolved = docker compose config
if ($LASTEXITCODE -ne 0) {
    throw "docker compose config failed"
}

$ResolvedText = $Resolved -join "`n"
if ($ResolvedText -notmatch "from vex_replay\.api import main") {
    throw "The override command was not applied by Docker Compose"
}

Write-Host "Compose command override verified."

docker compose down --remove-orphans
if ($LASTEXITCODE -ne 0) {
    throw "docker compose down failed"
}

docker compose up -d --force-recreate
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed"
}

$Deadline = (Get-Date).AddSeconds(120)
$Healthy = $false

while ((Get-Date) -lt $Deadline) {
    try {
        $Response = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8000/api/health" `
            -TimeoutSec 3

        if ($Response.status -eq "ok") {
            $Healthy = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
}

docker compose ps -a
docker compose logs --tail=100 app

if (-not $Healthy) {
    throw "The API did not become healthy within 120 seconds"
}

Write-Host ""
Write-Host "Dashboard is healthy:"
Write-Host "http://127.0.0.1:8000"
