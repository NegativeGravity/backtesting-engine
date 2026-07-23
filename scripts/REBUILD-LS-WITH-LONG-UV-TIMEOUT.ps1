param(
    [Parameter(Mandatory = $false)]
    [string]$ProjectRoot = "G:\PythonProject\backtesting-engine"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path

Push-Location $ProjectRoot
try {
    uv run python .\tools\patch_docker_uv_timeout.py --project-root .
    if ($LASTEXITCODE -ne 0) {
        throw "Dockerfile UV timeout patch failed."
    }

    docker compose build
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build failed."
    }

    docker compose up -d --force-recreate
    if ($LASTEXITCODE -ne 0) {
        throw "Docker startup failed."
    }
}
finally {
    Pop-Location
}
