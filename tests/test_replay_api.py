from pathlib import Path

from fastapi.testclient import TestClient

from vex_replay.api import create_app

RUN_ID = "run_xauusd_sdk_smoke_v1"


def test_replay_http_api() -> None:
    with TestClient(create_app(Path.cwd())) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        compatibility = client.get("/api/mt5/compatibility")
        assert compatibility.status_code == 200
        assert compatibility.json()["compatible"] is True
        catalog = client.get("/api/catalog")
        assert catalog.status_code == 200
        assert any(run["run_id"] == RUN_ID for run in catalog.json()["runs"])
        bootstrap = client.get(f"/api/runs/{RUN_ID}/bootstrap")
        assert bootstrap.status_code == 200
        assert bootstrap.json()["symbol"] == "XAUUSD"
        analytics = client.get(f"/api/runs/{RUN_ID}/analytics")
        assert analytics.status_code == 200
        assert analytics.json()["run_id"] == RUN_ID
        comparison = client.get("/api/analytics/compare", params={"run_id": RUN_ID})
        assert comparison.status_code == 200
        assert comparison.json()["rows"][0]["run_id"] == RUN_ID


def test_replay_websocket_controls() -> None:
    with (
        TestClient(create_app(Path.cwd())) as client,
        client.websocket_connect(f"/api/replay/{RUN_ID}/ws") as websocket,
    ):
        initial = websocket.receive_json()
        assert initial["type"] == "bootstrap"
        websocket.send_json({"action": "step_forward", "value": 3})
        frame = websocket.receive_json()
        assert frame["type"] == "frame"
        assert frame["data"]["cursor_sequence"] >= 3
        websocket.send_json({"action": "set_timeframe", "value": "H1"})
        reset = websocket.receive_json()
        assert reset["type"] == "bootstrap"
        assert reset["data"]["timeframe"] == "H1"
