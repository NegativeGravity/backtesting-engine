from pathlib import Path

import yaml


def test_compose_separates_bootstrap_engine_and_dashboard() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert {"bootstrap", "engine", "dashboard"}.issubset(services)
    assert (
        services["engine"]["depends_on"]["bootstrap"]["condition"]
        == "service_completed_successfully"
    )
    assert services["dashboard"]["depends_on"]["engine"]["condition"] == "service_healthy"
    assert services["engine"]["ports"] == ["${VEX_ENGINE_PORT:-8001}:8001"]
    assert services["dashboard"]["ports"] == ["${VEX_DASHBOARD_PORT:-8000}:8000"]
    assert "./strategies:/app/strategies:ro" in services["engine"]["volumes"]
    assert "build" in services["bootstrap"]
    assert "build" not in services["engine"]
    assert "build" not in services["dashboard"]


def test_dockerfile_uses_public_runtime_images_and_locked_dependencies() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "public.ecr.aws/docker/library/node:22-alpine AS dashboard-build" in dockerfile
    assert "public.ecr.aws/docker/library/python:3.12-slim AS runtime" in dockerfile
    assert "ghcr.io/astral-sh/uv:0.10.0 AS uv" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert 'CMD ["vex-engine"' in dockerfile
    assert "EXPOSE 8000 8001" in dockerfile


def test_docker_up_waits_for_separate_service_smoke_tests() -> None:
    up_script = Path("scripts/docker-up.ps1").read_text(encoding="utf-8")
    smoke_script = Path("scripts/docker-smoke.ps1").read_text(encoding="utf-8")
    assert "docker-smoke.ps1" in up_script
    assert "DashboardPort" in up_script
    assert "EnginePort" in up_script
    assert "/api/health" in smoke_script
    assert "/dashboard-health" in smoke_script
    assert "/api/engine/catalog" in smoke_script
    assert "/api/mt5/compatibility" in smoke_script
    assert "/analytics" in smoke_script
    assert "ClientWebSocket" in smoke_script
    assert 'websocket = "ok"' in smoke_script
