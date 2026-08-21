"""The v2 endpoint: one WebSocket carrying the whole API.

    ws://host/api/v2/ws?api_key=…&owner=…    (or the X-API-Key / X-Nodus-Owner headers)

Auth runs inline on the handshake: FastAPI's HTTP security dependencies do not
execute for a WebSocket upgrade, so `require_api_key` cannot be reused here.
The admin key is resolved once here too and carried on the connection, so an
action never has to re-derive it from the socket.

`owner` is *not* auth — it says which history this connection reads, not whether
it may connect. A client keeps one and sends it on every handshake; without one
the connection falls back to an identity derived from its address, so scripts
still see what they created. `ready.owner` echoes the resolved key, which is how
a client can tell whether the token it thinks it sent actually arrived. See
`app/services/ownership.py`.

`/api/v2/ws/{query_id}` is the same socket with one subscription pre-attached,
for a client that only wants to watch a single run.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.v2.actions import REGISTRY
from app.api.v2.session import Connection
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.schemas import stream as frames
from app.services import ownership
from app.services.errors import NotFound

logger = logging.getLogger(__name__)

router = APIRouter(tags=["v2"])


def _presented(websocket: WebSocket, header: str, param: str) -> str:
    return websocket.headers.get(header) or websocket.query_params.get(param) or ""


def _authorized(websocket: WebSocket) -> bool:
    if not settings.api_key:
        return True
    provided = _presented(websocket, "x-api-key", "api_key")
    return secrets.compare_digest(provided, settings.api_key)


def _is_admin(websocket: WebSocket) -> bool:
    """Whether this handshake carried ADMIN_API_KEY.

    Unset means nobody is an admin, so the inline `wait` path stays closed on a
    public deployment instead of opening by default.
    """
    if not settings.admin_api_key:
        return False
    return secrets.compare_digest(
        _presented(websocket, "x-admin-key", "admin_key"), settings.admin_api_key
    )


async def _serve(websocket: WebSocket, query_id: UUID | None = None) -> None:
    if not _authorized(websocket):
        await websocket.close(code=4401, reason="Invalid or missing API key")
        return

    await websocket.accept()
    connection = Connection(
        websocket,
        is_admin=_is_admin(websocket),
        owner_token=_presented(websocket, "x-nodus-owner", "owner"),
    )
    heartbeat = asyncio.create_task(connection.heartbeat_forever(), name="ws-heartbeat")

    try:
        resumed: list[str] = []
        if query_id is not None:
            # A run in the URL is still a read of somebody's run, so it is
            # checked before it is attached. Closed rather than answered: the
            # frame that would say "not yours" is the frame that confirms the id
            # exists, and there is no request id to attach an error to yet.
            try:
                async with AsyncSessionLocal() as db:
                    await ownership.require_query(
                        query_id,
                        db,
                        owner=connection.owner_key,
                        is_admin=connection.is_admin,
                    )
            except NotFound:
                await websocket.close(code=4404, reason="Query not found")
                return
            since = int(websocket.query_params.get("since") or 0)
            await connection.subscribe(query_id, since=since)
            resumed = connection.subscriptions()

        await connection.send_model(
            frames.ReadyFrame(
                heartbeat_seconds=settings.ws_heartbeat_seconds,
                actions=sorted(REGISTRY),
                resumed_subscriptions=resumed,
                owner=connection.owner_key,
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
