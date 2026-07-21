from __future__ import annotations

import json
import warnings
from pathlib import Path

from vex_orchestrator.api import create_app

RUN_ID = "run_xauusd_sma_cross_demo_v1"


def main() -> int:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Using `httpx` with `starlette.testclient` is deprecated.*",
        )
        from fastapi.testclient import TestClient

    project_root = Path.cwd()
    app = create_app(project_root)
    with TestClient(app) as client:
        health = client.get("/api/health")
        health.raise_for_status()
        compatibility = client.get("/api/mt5/compatibility")
        compatibility.raise_for_status()
        catalog = client.get("/api/catalog")
        catalog.raise_for_status()
        engine_catalog = client.get("/api/engine/catalog")
        engine_catalog.raise_for_status()
        bootstrap = client.get(f"/api/runs/{RUN_ID}/bootstrap")
        bootstrap.raise_for_status()
        analytics = client.get(f"/api/runs/{RUN_ID}/analytics")
        analytics.raise_for_status()
        payload = {
            "health": health.json(),
            "catalog_runs": len(catalog.json()["runs"]),
            "strategy_packages": len(engine_catalog.json()["strategies"]),
            "mt5_compatible": compatibility.json()["compatible"],
            "bootstrap_run_id": bootstrap.json()["run"]["run_id"],
            "analytics_run_id": analytics.json()["run_id"],
        }
    target = project_root / "data/replay/app-smoke-report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
