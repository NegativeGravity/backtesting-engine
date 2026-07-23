import argparse
import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import cast
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from websockets.asyncio.client import ClientConnection


def create_app(
    project_root: str | Path | None = None,
    engine_url: str | None = None,
) -> FastAPI:
    root = Path(project_root or Path.cwd()).resolve()
    upstream = (engine_url or os.environ.get("VEX_ENGINE_URL") or "http://127.0.0.1:8001").rstrip(
        "/"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        async with httpx.AsyncClient(base_url=upstream, timeout=60.0) as client:
            app.state.engine_client = client
            yield

    app = FastAPI(title="Vex Dashboard Gateway", version="1.2.0", lifespan=lifespan)

    @app.get("/dashboard-health")
    async def dashboard_health() -> dict[str, str]:
        client = cast(httpx.AsyncClient, app.state.engine_client)
        response = await client.get("/api/health")
        response.raise_for_status()
        return {"status": "ok", "service": "vex-dashboard", "engine": "ok"}

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def api_proxy(path: str, request: Request) -> Response:
        client = cast(httpx.AsyncClient, app.state.engine_client)
        body = await request.body()
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() in {"content-type", "accept", "authorization"}
        }
        response = await client.request(
            request.method,
            f"/api/{path}",
            params=request.query_params,
            content=body,
            headers=headers,
        )
        passthrough = {
            key: value
            for key, value in response.headers.items()
            if key.lower() in {"content-type", "cache-control", "etag"}
        }
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=passthrough,
        )

    @app.websocket("/api/{path:path}")
    async def websocket_proxy(websocket: WebSocket, path: str) -> None:
        await websocket.accept()
        target = _websocket_url(upstream, f"/api/{path}", dict(websocket.query_params))
        try:
            async with websockets.connect(target, max_size=16 * 1024 * 1024) as engine_socket:
                await _bridge_websockets(websocket, engine_socket)
        except WebSocketDisconnect:
            return
        except Exception as exc:
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=1011)

    dist = root / "apps/dashboard_web/dist"
    if not dist.exists():
        raise FileNotFoundError(f"dashboard build not found: {dist}")
    assets = dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        candidate = (dist / path).resolve()
        if path and candidate.is_relative_to(dist) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    return app


async def _bridge_websockets(client: WebSocket, engine: ClientConnection) -> None:
    async def client_to_engine() -> None:
        while True:
            message = await client.receive()
            if message["type"] == "websocket.disconnect":
                return
            text = message.get("text")
            data = message.get("bytes")
            if text is not None:
                await engine.send(text)
            elif data is not None:
                await engine.send(data)

    async def engine_to_client() -> None:
        async for message in engine:
            if isinstance(message, str):
                await client.send_text(message)
            else:
                await client.send_bytes(message)

    client_task = asyncio.create_task(client_to_engine())
    engine_task = asyncio.create_task(engine_to_client())
    done, pending = await asyncio.wait(
        {client_task, engine_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        with suppress(WebSocketDisconnect, websockets.ConnectionClosed):
            task.result()
    if engine_task in done:
        close_code = engine.close_code or 1000
        close_reason = engine.close_reason or ""
        with suppress(RuntimeError, WebSocketDisconnect):
            await client.close(code=close_code, reason=close_reason)
    elif client_task in done and engine.close_code is None:
        with suppress(websockets.ConnectionClosed):
            await engine.close(code=1000, reason="dashboard client disconnected")


def _websocket_url(base: str, path: str, query: dict[str, str]) -> str:
    parsed = urlsplit(base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((scheme, parsed.netloc, path, urlencode(query), ""))


def main() -> int:
    parser = argparse.ArgumentParser(prog="vex-dashboard")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--engine-url", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(
        create_app(args.project_root, args.engine_url),
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
