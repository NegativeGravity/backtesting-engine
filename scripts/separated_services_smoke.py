from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import websockets

RUN_ID = "run_final_separated_services_smoke_v1"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


def wait_http(url: str, timeout: float, process: subprocess.Popen[bytes]) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"service exited with code {process.returncode}: {url}")
        try:
            response = httpx.get(url, timeout=2.0)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise RuntimeError(f"service returned a non-object response: {url}")
        except Exception as exc:
            error = exc
            time.sleep(0.2)
    raise RuntimeError(f"service did not become ready: {url}: {error}")


async def stored_replay_check(port: int) -> dict[str, Any]:
    uri = (
        f"ws://127.0.0.1:{port}/api/replay/run_xauusd_sma_cross_demo_v1/ws"
        "?symbol=XAUUSD&timeframe=M1"
    )
    async with websockets.connect(uri, max_size=16 * 1024 * 1024) as websocket:
        initial = json.loads(await asyncio.wait_for(websocket.recv(), timeout=20))
        if initial.get("type") != "bootstrap":
            raise RuntimeError("stored replay did not return a bootstrap message")
        await websocket.send(json.dumps({"action": "step_forward", "value": 1}))
        frame = json.loads(await asyncio.wait_for(websocket.recv(), timeout=20))
        if frame.get("type") != "frame":
            raise RuntimeError("stored replay did not return a frame")
        return {
            "run_id": initial["data"]["run"]["run_id"],
            "cursor_sequence": frame["data"]["cursor_sequence"],
            "bars": len(frame["data"]["bars"]),
        }


async def live_replay_check(port: int) -> dict[str, Any]:
    uri = f"ws://127.0.0.1:{port}/api/replay/{RUN_ID}/ws?symbol=XAUUSD&timeframe=M1"
    async with websockets.connect(uri, max_size=16 * 1024 * 1024) as websocket:
        initial = json.loads(await asyncio.wait_for(websocket.recv(), timeout=20))
        if initial.get("type") != "bootstrap":
            raise RuntimeError("live replay did not return a bootstrap message")
        await websocket.send(json.dumps({"action": "step_forward", "value": 1}))
        advanced: dict[str, Any] | None = None
        for _ in range(10):
            message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=20))
            if message.get("type") == "frame" and message["data"].get("bars"):
                advanced = message["data"]
                break
        if advanced is None:
            raise RuntimeError("live replay did not advance one candle")
        await websocket.send(json.dumps({"action": "play"}))
        completed = False
        while True:
            try:
                message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=60))
            except websockets.ConnectionClosedOK:
                break
            if message.get("type") == "frame" and message["data"].get("frame_type") == "completed":
                completed = True
        return {
            "initial_cursor_sequence": initial["data"]["cursor_sequence"],
            "manual_cursor_sequence": advanced["cursor_sequence"],
            "manual_bars": len(advanced["bars"]),
            "completed_frame": completed,
        }


def terminate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    root = Path.cwd().resolve()
    engine_port = free_port()
    dashboard_port = free_port()
    live_root = root / "data/live-runs" / RUN_ID
    replay_root = root / "data/replay/runs" / RUN_ID
    shutil.rmtree(live_root, ignore_errors=True)
    shutil.rmtree(replay_root, ignore_errors=True)
    log_root = root / "data/replay/separated-services-smoke-logs"
    shutil.rmtree(log_root, ignore_errors=True)
    log_root.mkdir(parents=True, exist_ok=True)
    engine_log_path = log_root / "engine.log"
    dashboard_log_path = log_root / "dashboard.log"
    env = os.environ.copy()
    paths = [str(root / "src"), str(root / "strategies")]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    engine: subprocess.Popen[bytes] | None = None
    dashboard: subprocess.Popen[bytes] | None = None
    try:
        with (
            engine_log_path.open("wb") as engine_log,
            dashboard_log_path.open("wb") as dashboard_log,
        ):
            engine = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "vex_orchestrator.api",
                    "--project-root",
                    str(root),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(engine_port),
                ],
                cwd=root,
                env=env,
                stdout=engine_log,
                stderr=subprocess.STDOUT,
            )
            engine_health = wait_http(
                f"http://127.0.0.1:{engine_port}/api/health",
                60,
                engine,
            )
            dashboard = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "vex_dashboard.api",
                    "--project-root",
                    str(root),
                    "--engine-url",
                    f"http://127.0.0.1:{engine_port}",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(dashboard_port),
                ],
                cwd=root,
                env=env,
                stdout=dashboard_log,
                stderr=subprocess.STDOUT,
            )
            dashboard_health = wait_http(
                f"http://127.0.0.1:{dashboard_port}/dashboard-health",
                60,
                dashboard,
            )
            base = f"http://127.0.0.1:{dashboard_port}"
            root_response = httpx.get(base, timeout=10)
            root_response.raise_for_status()
            if "VEX" not in root_response.text and "root" not in root_response.text:
                raise RuntimeError("dashboard gateway did not serve the SPA")
            catalog = httpx.get(f"{base}/api/catalog", timeout=10)
            catalog.raise_for_status()
            stored = asyncio.run(stored_replay_check(dashboard_port))
            created = httpx.post(
                f"{base}/api/engine/runs",
                json={
                    "strategy_package_id": "sma_cross_demo",
                    "run_id": RUN_ID,
                    "max_close_batches": 2,
                    "start_paused": True,
                    "speed_bars_per_second": "500",
                },
                timeout=30,
            )
            created.raise_for_status()
            live = asyncio.run(live_replay_check(dashboard_port))
            deadline = time.monotonic() + 90
            state: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                response = httpx.get(f"{base}/api/engine/runs/{RUN_ID}", timeout=10)
                response.raise_for_status()
                state = response.json()
                if state["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.1)
            if state is None or state["status"] != "completed":
                raise RuntimeError(f"live run did not complete: {state}")
            analytics = httpx.get(f"{base}/api/runs/{RUN_ID}/analytics", timeout=30)
            analytics.raise_for_status()
            payload = {
                "engine_health": engine_health,
                "dashboard_health": dashboard_health,
                "catalog_runs": len(catalog.json()["runs"]),
                "stored_replay": stored,
                "live_replay": live,
                "live_status": state["status"],
                "live_replay_ready": state["replay_ready"],
                "analytics_run_id": analytics.json()["run_id"],
                "engine_port": engine_port,
                "dashboard_port": dashboard_port,
            }
    finally:
        terminate(dashboard)
        terminate(engine)
        shutil.rmtree(live_root, ignore_errors=True)
        shutil.rmtree(replay_root, ignore_errors=True)
    output = root / "data/replay/final-separated-services-smoke-report.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
