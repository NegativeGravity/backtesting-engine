# Docker Final Zero-to-Hero Guide for Windows

## Prerequisites

1. Install WSL 2:

```powershell
wsl --install
wsl --update
```

2. Install and start Docker Desktop.
3. Verify:

```powershell
docker version
docker compose version
```

## Build and start the full stack

```powershell
cd G:\PythonProject\backtesting-engine
powershell -ExecutionPolicy ByPass -File .\scripts\docker-up.ps1
```

Default endpoints:

```text
Dashboard  http://127.0.0.1:8000
Engine     http://127.0.0.1:8001
```

## Base images

The Dockerfile uses public ECR for official Python and Node images to avoid Docker Hub mirror and authentication failures:

```text
public.ecr.aws/docker/library/python:3.12-slim
public.ecr.aws/docker/library/node:22-alpine
ghcr.io/astral-sh/uv:0.10.0
```

## Build from scratch

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-up.ps1 -ForceRebuild
```

## Use different ports

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-up.ps1 `
  -DashboardPort 8080 `
  -EnginePort 8081
```

## Start services separately

```powershell
docker compose up -d bootstrap engine
docker compose up -d dashboard
```

## Inspect status and logs

```powershell
docker compose ps -a
docker compose logs --tail=200 bootstrap
docker compose logs -f engine
docker compose logs -f dashboard
```

## Run smoke checks

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-smoke.ps1
```

## Strategy hot-swap in Docker

The host `strategies` directory is mounted read-only at `/app/strategies`. Add or replace a strategy package on the host, then refresh the engine catalog:

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\strategy-refresh.ps1
```

No image rebuild or engine restart is required for a new run.

## Stop

```powershell
powershell -ExecutionPolicy ByPass -File .\scripts\docker-down.ps1
```

## Networking diagnostics

```powershell
Test-NetConnection public.ecr.aws -Port 443
Test-NetConnection ghcr.io -Port 443
Test-NetConnection registry.npmjs.org -Port 443
Test-NetConnection pypi.org -Port 443
```

If Docker Desktop uses a proxy, configure it under `Settings -> Resources -> Proxies`.
