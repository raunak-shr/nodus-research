"""The v2 endpoint: one WebSocket carrying the whole API.

    ws://host/api/v2/ws?api_key=…            (or the X-API-Key header)

Auth runs inline on the handshake: FastAPI's HTTP security dependencies do not
execute for a WebSocket upgrade, so `require_api_key` cannot be reused here.

`/api/v2/ws/{query_id}` is the same socket with one subscription pre-attached,
for a client that only wants to watch a single run.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.v2.actions import REGISTRY
from app.api.v2.session import Connection
from app.core.config import settings
from app.schemas import stream as frames

logger = logging.getLogger(__name__)

router = APIRouter(tags=["v2"])


def _authorized(websocket: WebSocket) -> bool:
    if not settings.api_key:
        return True
    provided = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
    return provided == settings.api_key


async def _serve(websocket: WebSocket, query_id: UUID | None = None) -> None:
    if not _authorized(websocket):
        await websocket.close(code=4401, reason="Invalid or missing API key")
        return

    await websocket.accept()
    connection = Connection(websocket)
    heartbeat = asyncio.create_task(connection.heartbeat_forever(), name="ws-heartbeat")

    try:
        resumed: list[str] = []
        if query_id is not None:
            since = int(websocket.query_params.get("since") or 0)
            await connection.subscribe(query_id, since=since)
            resumed = connection.subscriptions()

        await connection.send_model(
            frames.ReadyFrame(
                heartbeat_seconds=settings.ws_heartbeat_seconds,
                actions=sorted(REGISTRY),
                resumed_subscriptions=resumed,
            )
        )

        while True:
            raw = await websocket.receive_text()
            await connection.handle_text(raw)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - a broken socket must not surface as a 500
        logger.debug("v2 socket closed unexpectedly", exc_info=True)
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        await connection.aclose()
        with contextlib.suppress(RuntimeError):
            await websocket.close()


@router.websocket("/ws")
async def api_socket(websocket: WebSocket) -> None:
    """Full v2 API: send `{"action": "meta.describe"}` for the action catalogue."""
    await _serve(websocket)


@router.websocket("/ws/{query_id}")
async def api_socket_for_query(websocket: WebSocket, query_id: UUID) -> None:
    """Full v2 API with this query's progress already subscribed."""
    await _serve(websocket, query_id=query_id)
