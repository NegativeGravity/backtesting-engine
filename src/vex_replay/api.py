import argparse
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, cast

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from vex_contracts.mt5 import Mt5CompatibilityReport
from vex_contracts.replay import ReplayControlCommand
from vex_contracts.serialization import load_json
from vex_contracts.timeframes import Timeframe
from vex_replay.repository import ReplayRunNotFoundError, ReplayRunRepository
from vex_replay.session import ReplaySession


def create_app(project_root: str | Path | None = None) -> FastAPI:
    root = Path(project_root or Path.cwd()).resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.replay_repository = ReplayRunRepository(root)
        yield

    app = FastAPI(
        title="Vex Replay API",
        version="1.2.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def repository() -> ReplayRunRepository:
        return cast(ReplayRunRepository, app.state.replay_repository)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "vex-replay"}

    @app.get("/api/catalog")
    def catalog() -> Any:
        return repository().catalog()

    @app.post("/api/catalog/refresh")
    def refresh_catalog() -> Any:
        repository().refresh()
        return repository().catalog()

    @app.get("/api/mt5/compatibility")
    def mt5_compatibility() -> Mt5CompatibilityReport:
        path = root / "data/cache/mt5-compatibility-report.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="MT5 compatibility report not found")
        return Mt5CompatibilityReport.model_validate(load_json(path))

    @app.get("/api/runs/{run_id}/bootstrap")
    def bootstrap(
        run_id: str,
        symbol: str | None = None,
        timeframe: Timeframe | None = None,
        cursor_time_ns: int | None = None,
        history_count: int = Query(default=500, ge=50, le=5000),
    ) -> Any:
        try:
            return repository().bootstrap(
                run_id,
                symbol,
                timeframe,
                cursor_time_ns,
                history_count,
            )
        except ReplayRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}") from exc

    @app.get("/api/runs/{run_id}/bars")
    def bars(
        run_id: str,
        symbol: str,
        timeframe: Timeframe,
        start_exclusive_ns: int,
        end_inclusive_ns: int,
        limit: int = Query(default=5000, ge=1, le=50000),
    ) -> Any:
        try:
            return repository().bars_for_view(
                run_id,
                symbol,
                timeframe,
                start_exclusive_ns,
                end_inclusive_ns,
                limit,
            )
        except ReplayRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}") from exc

    @app.get("/api/runs/{run_id}/timeline")
    def timeline(
        run_id: str,
        start_exclusive_ns: int,
        end_inclusive_ns: int,
        limit: int = Query(default=10000, ge=1, le=100000),
    ) -> Any:
        try:
            return repository().timeline_between(
                run_id,
                start_exclusive_ns,
                end_inclusive_ns,
                limit,
            )
        except ReplayRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}") from exc

    @app.get("/api/runs/{run_id}/analytics")
    def analytics(run_id: str, end_time_ns: int | None = None) -> Any:
        try:
            return repository().analytics(run_id, end_time_ns)
        except ReplayRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}") from exc

    @app.get("/api/analytics/compare")
    def analytics_compare(run_id: Annotated[list[str] | None, Query()] = None) -> Any:
        try:
            return repository().analytics_comparison(tuple(run_id or ()))
        except ReplayRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"run not found: {exc.args[0]}") from exc

    @app.websocket("/api/replay/{run_id}/ws")
    async def replay_socket(
        websocket: WebSocket,
        run_id: str,
        symbol: str | None = None,
        timeframe: Timeframe | None = None,
    ) -> None:
        await websocket.accept()
        try:
            session, initial = ReplaySession.create(
                repository(),
                run_id,
                symbol,
                timeframe,
            )
        except ReplayRunNotFoundError:
            await websocket.send_json({"type": "error", "detail": f"run not found: {run_id}"})
            await websocket.close(code=4404)
            return
        await websocket.send_json({"type": "bootstrap", "data": initial.model_dump(mode="json")})
        try:
            while True:
                timeout = max(0.02, 0.5 / float(session.speed)) if session.playing else None
                try:
                    message = (
                        await asyncio.wait_for(websocket.receive_json(), timeout=timeout)
                        if timeout is not None
                        else await websocket.receive_json()
                    )
                    command = ReplayControlCommand.model_validate(message)
                    await _apply_command(websocket, session, command)
                except TimeoutError:
                    batch_size = max(1, min(100, int(session.speed / Decimal("25")) or 1))
                    frame = session.step_forward(batch_size)
                    await websocket.send_json(
                        {"type": "frame", "data": frame.model_dump(mode="json")}
                    )
        except WebSocketDisconnect:
            return
        except ValidationError as exc:
            await websocket.send_json({"type": "error", "detail": str(exc)})
        except ValueError as exc:
            await websocket.send_json({"type": "error", "detail": str(exc)})

    dist = root / "apps/dashboard_web/dist"
    if dist.exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            del path
            return FileResponse(dist / "index.html")

    return app


async def _apply_command(
    websocket: WebSocket,
    session: ReplaySession,
    command: ReplayControlCommand,
) -> None:
    if command.action == "play":
        result = session.play()
        await websocket.send_json({"type": "frame", "data": result.model_dump(mode="json")})
        return
    if command.action == "pause":
        result = session.pause()
        await websocket.send_json({"type": "frame", "data": result.model_dump(mode="json")})
        return
    if command.action == "step_forward":
        count = int(command.value or 1)
        result = session.step_forward(count)
        await websocket.send_json({"type": "frame", "data": result.model_dump(mode="json")})
        return
    if command.action == "step_backward":
        result = session.step_backward()
        await websocket.send_json({"type": "bootstrap", "data": result.model_dump(mode="json")})
        return
    if command.action == "seek_time":
        if command.value is None:
            raise ValueError("seek_time requires a value")
        result = session.seek_time(int(command.value))
        await websocket.send_json({"type": "bootstrap", "data": result.model_dump(mode="json")})
        return
    if command.action == "seek_progress":
        if command.value is None:
            raise ValueError("seek_progress requires a value")
        result = session.seek_progress(Decimal(str(command.value)))
        await websocket.send_json({"type": "bootstrap", "data": result.model_dump(mode="json")})
        return
    if command.action == "set_speed":
        if command.value is None:
            raise ValueError("set_speed requires a value")
        result = session.set_speed(Decimal(str(command.value)))
        await websocket.send_json({"type": "frame", "data": result.model_dump(mode="json")})
        return
    if command.action == "set_timeframe":
        if command.value is None:
            raise ValueError("set_timeframe requires a value")
        result = session.set_timeframe(Timeframe(str(command.value)))
        await websocket.send_json({"type": "bootstrap", "data": result.model_dump(mode="json")})
        return
    if command.action == "reset":
        result = session.reset()
        await websocket.send_json({"type": "bootstrap", "data": result.model_dump(mode="json")})
        return
    raise ValueError(f"unsupported replay action: {command.action}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="vex-api")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    if args.reload:
        uvicorn.run(
            "vex_replay.api:create_app",
            host=args.host,
            port=args.port,
            reload=True,
            factory=True,
        )
    else:
        uvicorn.run(
            create_app(args.project_root),
            host=args.host,
            port=args.port,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
