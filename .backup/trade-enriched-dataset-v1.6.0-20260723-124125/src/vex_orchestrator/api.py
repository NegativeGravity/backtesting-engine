import argparse
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, cast

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from vex_contracts.mt5 import Mt5CompatibilityReport
from vex_contracts.replay import ReplayControlCommand
from vex_contracts.serialization import load_json
from vex_contracts.timeframes import Timeframe
from vex_orchestrator.catalog import StrategyPackageCatalog, StrategyPackageNotFoundError
from vex_orchestrator.manager import (
    LiveBacktestJob,
    LiveBacktestManager,
    LiveRunNotFoundError,
)
from vex_orchestrator.models import LiveRunControlCommand, LiveRunCreateRequest
from vex_replay.repository import ReplayRunNotFoundError, ReplayRunRepository
from vex_replay.session import ReplaySession


def create_app(project_root: str | Path | None = None) -> FastAPI:
    root = Path(project_root or Path.cwd()).resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        repository = ReplayRunRepository(root)
        catalog = StrategyPackageCatalog(root)
        manager = LiveBacktestManager(root, catalog, repository)
        app.state.replay_repository = repository
        app.state.strategy_catalog = catalog
        app.state.live_manager = manager
        try:
            yield
        finally:
            manager.shutdown()

    app = FastAPI(
        title="Vex Backtest Engine API",
        version="1.5.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def repository() -> ReplayRunRepository:
        return cast(ReplayRunRepository, app.state.replay_repository)

    def manager() -> LiveBacktestManager:
        return cast(LiveBacktestManager, app.state.live_manager)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "vex-backtest-engine",
            "mode": "million-candle-streaming",
        }

    @app.get("/api/catalog")
    def catalog() -> Any:
        return manager().replay_catalog()

    @app.post("/api/catalog/refresh")
    def refresh_catalog() -> Any:
        repository().refresh()
        manager().catalog.refresh()
        return manager().replay_catalog()

    @app.get("/api/engine/catalog")
    def engine_catalog() -> Any:
        return manager().catalog_response()

    @app.post("/api/engine/strategies/refresh")
    def refresh_strategies() -> Any:
        try:
            return manager().refresh_strategies()
        except (FileNotFoundError, ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/engine/runs", status_code=201)
    def create_live_run(request: LiveRunCreateRequest) -> Any:
        try:
            return manager().create(request)
        except StrategyPackageNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"strategy package not found: {request.strategy_package_id}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/engine/runs/{run_id}")
    def live_run_state(run_id: str) -> Any:
        try:
            return manager().get(run_id).state()
        except LiveRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"live run not found: {run_id}") from exc

    @app.post("/api/engine/runs/{run_id}/control")
    def control_live_run(run_id: str, command: LiveRunControlCommand) -> Any:
        try:
            return manager().control(run_id, command)
        except LiveRunNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"live run not found: {run_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
            job = manager().get(run_id)
        except LiveRunNotFoundError:
            job = None
        if job is not None and not job.state().replay_ready:
            del cursor_time_ns, history_count
            try:
                return job.bootstrap(symbol, timeframe)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
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
            job = manager().get(run_id)
        except LiveRunNotFoundError:
            job = None
        if job is not None and not job.state().replay_ready:
            try:
                return job.bars_for_view(
                    symbol,
                    timeframe,
                    start_exclusive_ns,
                    end_inclusive_ns,
                    limit,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
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
            job = manager().get(run_id)
        except LiveRunNotFoundError:
            job = None
        if job is not None and not job.state().replay_ready:
            return job.timeline_between(start_exclusive_ns, end_inclusive_ns, limit)
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
            try:
                state = manager().get(run_id).state()
            except LiveRunNotFoundError:
                raise HTTPException(status_code=404, detail=f"run not found: {run_id}") from exc
            raise HTTPException(
                status_code=409,
                detail=(
                    f"analytics are available after finalization; current status: {state.status}"
                ),
            ) from exc

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
            job = manager().get(run_id)
        except LiveRunNotFoundError:
            job = None
        if job is not None and not job.state().replay_ready:
            await _live_socket(websocket, job, symbol, timeframe)
            return
        await _stored_replay_socket(websocket, repository(), run_id, symbol, timeframe)

    return app


async def _live_socket(
    websocket: WebSocket,
    job: LiveBacktestJob,
    symbol: str | None,
    timeframe: Timeframe | None,
) -> None:
    loop = asyncio.get_running_loop()
    subscriber, bootstrap = job.subscribe(loop, symbol, timeframe)
    await websocket.send_json({"type": "bootstrap", "data": bootstrap.model_dump(mode="json")})
    receive_task = asyncio.create_task(websocket.receive_json())
    queue_task = asyncio.create_task(job.next_message(subscriber))
    try:
        while True:
            done, _ = await asyncio.wait(
                {receive_task, queue_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if queue_task in done:
                queued_message = queue_task.result()
                await websocket.send_json(queued_message)
                frame_data = queued_message.get("data")
                if (
                    queued_message.get("type") == "frame"
                    and isinstance(frame_data, dict)
                    and frame_data.get("frame_type") == "completed"
                    and job.state().replay_ready
                ):
                    await websocket.close(code=1000)
                    return
                queue_task = asyncio.create_task(job.next_message(subscriber))
            if receive_task in done:
                message = receive_task.result()
                command = ReplayControlCommand.model_validate(message)
                if command.action == "set_timeframe":
                    if command.value is None:
                        raise ValueError("set_timeframe requires a value")
                    fresh = job.update_subscriber_timeframe(
                        subscriber,
                        Timeframe(str(command.value)),
                    )
                    await websocket.send_json(
                        {"type": "bootstrap", "data": fresh.model_dump(mode="json")}
                    )
                elif command.action == "seek_time":
                    raise ValueError("live runs support seek_progress, not seek_time")
                else:
                    translated = LiveRunControlCommand.model_validate(command.model_dump())
                    job.control(translated)
                    frame = job.state_frame()
                    await websocket.send_json(
                        {"type": "frame", "data": frame.model_dump(mode="json")}
                    )
                receive_task = asyncio.create_task(websocket.receive_json())
    except WebSocketDisconnect:
        return
    except (ValidationError, ValueError) as exc:
        await websocket.send_json({"type": "error", "detail": str(exc)})
    finally:
        receive_task.cancel()
        queue_task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(receive_task, queue_task, return_exceptions=True)
        job.unsubscribe(subscriber)


async def _stored_replay_socket(
    websocket: WebSocket,
    repository: ReplayRunRepository,
    run_id: str,
    symbol: str | None,
    timeframe: Timeframe | None,
) -> None:
    try:
        session, initial = ReplaySession.create(repository, run_id, symbol, timeframe)
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
                await _apply_replay_command(websocket, session, command)
            except TimeoutError:
                batch_size = max(1, min(100, int(session.speed / Decimal("25")) or 1))
                frame = session.step_forward(batch_size)
                await websocket.send_json({"type": "frame", "data": frame.model_dump(mode="json")})
    except WebSocketDisconnect:
        return
    except (ValidationError, ValueError) as exc:
        await websocket.send_json({"type": "error", "detail": str(exc)})


async def _apply_replay_command(
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
        result = session.step_forward(int(command.value or 1))
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
    parser = argparse.ArgumentParser(prog="vex-engine")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    if args.reload:
        uvicorn.run(
            "vex_orchestrator.api:create_app",
            host=args.host,
            port=args.port,
            reload=True,
            factory=True,
        )
    else:
        uvicorn.run(create_app(args.project_root), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
