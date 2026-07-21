import asyncio
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from vex_dashboard.api import _bridge_websockets, create_app


def test_dashboard_gateway_serves_built_spa(project_root: Path) -> None:
    with TestClient(create_app(project_root, "http://127.0.0.1:65530")) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class _EngineClosingClient:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed: tuple[int, str] | None = None

    async def receive(self) -> dict[str, str]:
        await asyncio.Event().wait()
        raise AssertionError

    async def send_text(self, message: str) -> None:
        self.sent.append(message)

    async def send_bytes(self, message: bytes) -> None:
        raise AssertionError(message)

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)


class _EngineClosingUpstream:
    close_code = 1000
    close_reason = "complete"

    def __aiter__(self) -> Any:
        async def messages() -> Any:
            yield '{"type":"frame"}'

        return messages()

    async def send(self, message: str | bytes) -> None:
        raise AssertionError(message)

    async def close(self, code: int, reason: str) -> None:
        raise AssertionError((code, reason))


class _ClientClosingClient:
    async def receive(self) -> dict[str, str]:
        return {"type": "websocket.disconnect"}

    async def send_text(self, message: str) -> None:
        raise AssertionError(message)

    async def send_bytes(self, message: bytes) -> None:
        raise AssertionError(message)

    async def close(self, code: int, reason: str) -> None:
        raise AssertionError((code, reason))


class _ClientClosingUpstream:
    close_code: int | None = None
    close_reason: str | None = None

    def __init__(self) -> None:
        self.closed: tuple[int, str] | None = None

    def __aiter__(self) -> Any:
        async def messages() -> Any:
            await asyncio.Event().wait()
            yield ""

        return messages()

    async def send(self, message: str | bytes) -> None:
        raise AssertionError(message)

    async def close(self, code: int, reason: str) -> None:
        self.close_code = code
        self.close_reason = reason
        self.closed = (code, reason)


def test_dashboard_gateway_relays_upstream_websocket_close() -> None:
    client = _EngineClosingClient()
    engine = _EngineClosingUpstream()
    asyncio.run(_bridge_websockets(cast(Any, client), cast(Any, engine)))
    assert client.sent == ['{"type":"frame"}']
    assert client.closed == (1000, "complete")


def test_dashboard_gateway_closes_upstream_after_client_disconnect() -> None:
    client = _ClientClosingClient()
    engine = _ClientClosingUpstream()
    asyncio.run(_bridge_websockets(cast(Any, client), cast(Any, engine)))
    assert engine.closed == (1000, "dashboard client disconnected")
