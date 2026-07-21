import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from vex_orchestrator.api import create_app
from vex_orchestrator.catalog import StrategyPackageCatalog


def test_strategy_catalog_exposes_only_enabled_drop_in_packages(project_root: Path) -> None:
    catalog = StrategyPackageCatalog(project_root)
    summaries = catalog.summaries()
    assert [item.package_id for item in summaries] == ["sma_cross_demo"]
    assert summaries[0].entrypoint == "sma_cross_demo.strategy:SmaCrossStrategy"
    assert summaries[0].package_path == "sma_cross_demo"


def test_engine_creates_paused_live_run_and_steps_one_batch(project_root: Path) -> None:
    run_id = "run_engine_api_step_test_v1"
    live_root = project_root / "data/live-runs" / run_id
    replay_root = project_root / "data/replay/runs" / run_id
    shutil.rmtree(live_root, ignore_errors=True)
    shutil.rmtree(replay_root, ignore_errors=True)
    try:
        with TestClient(create_app(project_root)) as client:
            created = client.post(
                "/api/engine/runs",
                json={
                    "strategy_package_id": "sma_cross_demo",
                    "run_id": run_id,
                    "max_close_batches": 10,
                    "start_paused": True,
                    "speed_bars_per_second": 100,
                },
            )
            assert created.status_code == 201
            assert created.json()["run_id"] == run_id

            with client.websocket_connect(f"/api/replay/{run_id}/ws") as websocket:
                initial = websocket.receive_json()
                assert initial["type"] == "bootstrap"
                assert initial["data"]["cursor_sequence"] == 0
                websocket.send_json({"action": "step_forward", "value": 1})

                advanced = None
                for _ in range(5):
                    message = websocket.receive_json()
                    if message["type"] == "frame" and message["data"]["bars"]:
                        advanced = message
                        break
                assert advanced is not None
                assert advanced["data"]["cursor_sequence"] == 1
                assert len(advanced["data"]["bars"]) == 1

            state = client.get(f"/api/engine/runs/{run_id}")
            assert state.status_code == 200
            assert state.json()["processed_close_batches"] == 1
            assert state.json()["playing"] is False
    finally:
        shutil.rmtree(live_root, ignore_errors=True)
        shutil.rmtree(replay_root, ignore_errors=True)


def test_completed_live_run_is_immediately_available_to_replay_repository(
    project_root: Path,
) -> None:
    run_id = "run_engine_finalization_visibility_test_v1"
    live_root = project_root / "data/live-runs" / run_id
    replay_root = project_root / "data/replay/runs" / run_id
    shutil.rmtree(live_root, ignore_errors=True)
    shutil.rmtree(replay_root, ignore_errors=True)
    try:
        with TestClient(create_app(project_root)) as client:
            created = client.post(
                "/api/engine/runs",
                json={
                    "strategy_package_id": "sma_cross_demo",
                    "run_id": run_id,
                    "max_close_batches": 2,
                    "start_paused": False,
                    "speed_bars_per_second": 500,
                },
            )
            assert created.status_code == 201

            deadline = time.monotonic() + 60
            state = created.json()
            while state["status"] not in {"completed", "failed", "cancelled"}:
                assert time.monotonic() < deadline
                time.sleep(0.05)
                response = client.get(f"/api/engine/runs/{run_id}")
                assert response.status_code == 200
                state = response.json()

            assert state["status"] == "completed", state
            assert state["replay_ready"] is True

            analytics = client.get(f"/api/runs/{run_id}/analytics")
            assert analytics.status_code == 200
            assert analytics.json()["run_id"] == run_id

            bootstrap = client.get(f"/api/runs/{run_id}/bootstrap")
            assert bootstrap.status_code == 200
            assert bootstrap.json()["run"]["run_id"] == run_id
    finally:
        shutil.rmtree(live_root, ignore_errors=True)
        shutil.rmtree(replay_root, ignore_errors=True)


def test_engine_rejects_invalid_live_run_time_window(project_root: Path) -> None:
    with TestClient(create_app(project_root)) as client:
        response = client.post(
            "/api/engine/runs",
            json={
                "strategy_package_id": "sma_cross_demo",
                "run_id": "run_invalid_window_test_v1",
                "start_time": "2026-01-02T00:00:00Z",
                "end_time": "2025-01-02T00:00:00Z",
                "max_close_batches": 1,
            },
        )
        assert response.status_code == 409
        assert "start_time must be earlier than end_time" in response.json()["detail"]


def test_completed_live_run_rejects_live_controls(project_root: Path) -> None:
    run_id = "run_engine_terminal_control_test_v1"
    live_root = project_root / "data/live-runs" / run_id
    replay_root = project_root / "data/replay/runs" / run_id
    shutil.rmtree(live_root, ignore_errors=True)
    shutil.rmtree(replay_root, ignore_errors=True)
    try:
        with TestClient(create_app(project_root)) as client:
            created = client.post(
                "/api/engine/runs",
                json={
                    "strategy_package_id": "sma_cross_demo",
                    "run_id": run_id,
                    "max_close_batches": 1,
                    "start_paused": False,
                    "speed_bars_per_second": 500,
                },
            )
            assert created.status_code == 201
            deadline = time.monotonic() + 60
            state = created.json()
            while state["status"] not in {"completed", "failed", "cancelled"}:
                assert time.monotonic() < deadline
                time.sleep(0.05)
                state_response = client.get(f"/api/engine/runs/{run_id}")
                assert state_response.status_code == 200
                state = state_response.json()
            assert state["status"] == "completed", state
            control = client.post(
                f"/api/engine/runs/{run_id}/control",
                json={"action": "step_backward"},
            )
            assert control.status_code == 422
            assert "finalized replay" in control.json()["detail"]
    finally:
        shutil.rmtree(live_root, ignore_errors=True)
        shutil.rmtree(replay_root, ignore_errors=True)


def test_live_run_rewind_and_finalization_use_snapshotted_strategy_source(
    project_root: Path,
) -> None:
    run_id = "run_engine_source_snapshot_test_v1"
    live_root = project_root / "data/live-runs" / run_id
    replay_root = project_root / "data/replay/runs" / run_id
    source_path = project_root / "strategies/sma_cross_demo/strategy.py"
    original_source = source_path.read_bytes()
    shutil.rmtree(live_root, ignore_errors=True)
    shutil.rmtree(replay_root, ignore_errors=True)
    try:
        with TestClient(create_app(project_root)) as client:
            created = client.post(
                "/api/engine/runs",
                json={
                    "strategy_package_id": "sma_cross_demo",
                    "run_id": run_id,
                    "max_close_batches": 2,
                    "start_paused": True,
                    "speed_bars_per_second": 500,
                },
            )
            assert created.status_code == 201
            snapshot = live_root / "strategy-source/sma_cross_demo/strategy.py"
            assert snapshot.read_bytes() == original_source

            source_path.write_text(
                'raise RuntimeError("modified package source must not be imported")\n',
                encoding="utf-8",
            )

            forward = client.post(
                f"/api/engine/runs/{run_id}/control",
                json={"action": "step_forward", "value": 1},
            )
            assert forward.status_code == 200
            deadline = time.monotonic() + 60
            state = forward.json()
            while state["processed_close_batches"] < 1:
                assert time.monotonic() < deadline
                time.sleep(0.05)
                state = client.get(f"/api/engine/runs/{run_id}").json()

            rewind = client.post(
                f"/api/engine/runs/{run_id}/control",
                json={"action": "step_backward"},
            )
            assert rewind.status_code == 200
            while state["processed_close_batches"] != 0 or state["status"] == "rewinding":
                assert time.monotonic() < deadline
                time.sleep(0.05)
                state = client.get(f"/api/engine/runs/{run_id}").json()

            play = client.post(
                f"/api/engine/runs/{run_id}/control",
                json={"action": "play"},
            )
            assert play.status_code == 200
            while state["status"] not in {"completed", "failed", "cancelled"}:
                assert time.monotonic() < deadline
                time.sleep(0.05)
                state = client.get(f"/api/engine/runs/{run_id}").json()

            assert state["status"] == "completed", state
            manifest = (replay_root / "manifest.json").read_text(encoding="utf-8")
            assert '"strategy_source_path"' in manifest
            assert '"strategy_source_sha256"' in manifest
            bundled = replay_root / "strategy-source/sma_cross_demo/strategy.py"
            assert bundled.read_bytes() == original_source
    finally:
        source_path.write_bytes(original_source)
        shutil.rmtree(live_root, ignore_errors=True)
        shutil.rmtree(replay_root, ignore_errors=True)


def test_engine_rejects_existing_replay_id_without_creating_live_workdir(
    project_root: Path,
) -> None:
    run_id = "run_xauusd_sma_cross_demo_v1"
    live_root = project_root / "data/live-runs" / run_id
    shutil.rmtree(live_root, ignore_errors=True)
    with TestClient(create_app(project_root)) as client:
        response = client.post(
            "/api/engine/runs",
            json={
                "strategy_package_id": "sma_cross_demo",
                "run_id": run_id,
                "max_close_batches": 1,
            },
        )
        assert response.status_code == 409
        assert "replay run already exists" in response.json()["detail"]
    assert not live_root.exists()


def test_live_websocket_transitions_to_finalized_replay(project_root: Path) -> None:
    run_id = "run_engine_socket_transition_test_v1"
    live_root = project_root / "data/live-runs" / run_id
    replay_root = project_root / "data/replay/runs" / run_id
    shutil.rmtree(live_root, ignore_errors=True)
    shutil.rmtree(replay_root, ignore_errors=True)
    try:
        with TestClient(create_app(project_root)) as client:
            created = client.post(
                "/api/engine/runs",
                json={
                    "strategy_package_id": "sma_cross_demo",
                    "run_id": run_id,
                    "max_close_batches": 1,
                    "start_paused": True,
                    "speed_bars_per_second": 500,
                },
            )
            assert created.status_code == 201
            completed_frame_seen = False
            with client.websocket_connect(f"/api/replay/{run_id}/ws") as websocket:
                assert websocket.receive_json()["type"] == "bootstrap"
                websocket.send_json({"action": "play"})
                for _ in range(20):
                    try:
                        message = websocket.receive_json()
                    except WebSocketDisconnect:
                        break
                    if message["type"] == "frame" and message["data"]["frame_type"] == "completed":
                        completed_frame_seen = True
                else:
                    raise AssertionError("live WebSocket did not close after finalization")
            assert completed_frame_seen

            deadline = time.monotonic() + 60
            state = client.get(f"/api/engine/runs/{run_id}").json()
            while state["status"] != "completed":
                assert time.monotonic() < deadline
                time.sleep(0.05)
                state = client.get(f"/api/engine/runs/{run_id}").json()

            with client.websocket_connect(f"/api/replay/{run_id}/ws") as websocket:
                bootstrap = websocket.receive_json()
                assert bootstrap["type"] == "bootstrap"
                assert bootstrap["data"]["run"]["run_id"] == run_id
    finally:
        shutil.rmtree(live_root, ignore_errors=True)
        shutil.rmtree(replay_root, ignore_errors=True)
