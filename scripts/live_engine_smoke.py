from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from vex_orchestrator.api import create_app

RUN_ID = "run_final_live_engine_smoke_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def source_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        candidate
        for candidate in root.rglob("*")
        if candidate.is_file()
        and "__pycache__" not in candidate.parts
        and candidate.suffix.lower() not in {".pyc", ".pyo"}
    ):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def main() -> int:
    root = Path.cwd().resolve()
    live_root = root / "data/live-runs" / RUN_ID
    replay_root = root / "data/replay/runs" / RUN_ID
    shutil.rmtree(live_root, ignore_errors=True)
    shutil.rmtree(replay_root, ignore_errors=True)
    payload: dict[str, object]
    try:
        with TestClient(create_app(root)) as client:
            created = client.post(
                "/api/engine/runs",
                json={
                    "strategy_package_id": "sma_cross_demo",
                    "run_id": RUN_ID,
                    "max_close_batches": 50,
                    "start_paused": True,
                    "speed_bars_per_second": "500",
                },
            )
            created.raise_for_status()
            with client.websocket_connect(f"/api/replay/{RUN_ID}/ws") as websocket:
                initial = websocket.receive_json()
                if initial["type"] != "bootstrap":
                    raise RuntimeError("live run did not provide a bootstrap frame")
                websocket.send_json({"action": "step_forward", "value": 1})
                forward = None
                for _ in range(10):
                    message = websocket.receive_json()
                    if message["type"] == "frame" and message["data"]["bars"]:
                        forward = message["data"]
                        break
                if forward is None or forward["cursor_sequence"] != 1:
                    raise RuntimeError("step_forward did not advance exactly one execution candle")
                websocket.send_json({"action": "step_backward"})
                rewind = None
                for _ in range(10):
                    message = websocket.receive_json()
                    if message["type"] == "bootstrap":
                        rewind = message["data"]
                        break
                if rewind is None or rewind["cursor_sequence"] != 0:
                    raise RuntimeError("step_backward did not reconstruct the initial state")
                websocket.send_json({"action": "play"})

            deadline = time.monotonic() + 180
            state = None
            while time.monotonic() < deadline:
                response = client.get(f"/api/engine/runs/{RUN_ID}")
                response.raise_for_status()
                state = response.json()
                if state["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.1)
            if state is None or state["status"] != "completed":
                raise RuntimeError(f"live run did not complete: {state}")
            analytics = client.get(f"/api/runs/{RUN_ID}/analytics")
            analytics.raise_for_status()
            bootstrap = client.get(f"/api/runs/{RUN_ID}/bootstrap")
            bootstrap.raise_for_status()
            manifest_path = replay_root / "manifest.json"
            database_path = replay_root / "replay.sqlite3"
            analytics_path = replay_root / "analytics-report.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source_path_value = manifest.get("strategy_source_path")
            source_hash_value = manifest.get("strategy_source_sha256")
            if not isinstance(source_path_value, str) or not isinstance(source_hash_value, str):
                raise RuntimeError("final replay is missing the strategy source snapshot")
            source_root = root / source_path_value
            if not source_root.is_dir():
                raise RuntimeError("strategy source snapshot path does not exist")
            if source_tree_sha256(source_root) != source_hash_value:
                raise RuntimeError("strategy source snapshot hash mismatch")
            payload = {
                "run_id": RUN_ID,
                "status": state["status"],
                "replay_ready": state["replay_ready"],
                "processed_close_batches": state["processed_close_batches"],
                "processed_execution_bars": state["processed_execution_bars"],
                "manual_step_cursor_sequence": forward["cursor_sequence"],
                "rewind_cursor_sequence": rewind["cursor_sequence"],
                "strategy_package": "sma_cross_demo",
                "strategy_digest": bootstrap.json()["strategy_report"]["deterministic_digest"],
                "strategy_source_path": source_path_value,
                "strategy_source_sha256": source_hash_value,
                "replay_database_sha256": sha256(database_path),
                "analytics_sha256": sha256(analytics_path),
                "manifest_sha256": sha256(manifest_path),
                "analytics_run_id": analytics.json()["run_id"],
            }
    finally:
        shutil.rmtree(live_root, ignore_errors=True)
        shutil.rmtree(replay_root, ignore_errors=True)
    target = root / "data/replay/final-live-engine-smoke-report.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
