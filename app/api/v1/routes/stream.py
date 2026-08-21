"""WebSocket progress streaming.

Kept in its own router because FastAPI's HTTP security dependencies (the
`X-API-Key` scheme used by every other route) cannot run on a WebSocket
handshake — auth is enforced inline here instead. Ownership is too, and for
the same reason: watching a run is a read of somebody's research, so a query
id alone must not be enough to attach to it. The owner token arrives as
`?owner=` or `X-Nodus-Owner`, exactly as on the v2 socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.events import hub
from app.db.session import AsyncSessionLocal
from app.models.query import QueryStatus
from app.services import ownership
from app.services.errors import NotFound

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/queries", tags=["queries"])

_HEARTBEAT_SECONDS = 30.0
_TERMINAL = {str(QueryStatus.completed), str(QueryStatus.failed)}


async def _owns_the_run(websocket: WebSocket, query_id: UUID) -> bool:
    """Whether this handshake may watch this run.

    Same rule as every other read of a query: the caller's owner key has to
    match the one the run was submitted under. A refusal closes the socket
    rather than streaming an empty channel, so a client is told rather than
    left waiting for events that will never come.
    """
    owner = ownership.resolve_owner(
        websocket.headers.get("x-nodus-owner") or websocket.query_params.get("owner"),
        client_host=websocket.client.host if websocket.client else None,
        forwarded_for=websocket.headers.get("x-forwarded-for"),
    )
    try:
        async with AsyncSessionLocal() as db:
            await ownership.require_query(query_id, db, owner=owner)
    except NotFound:
        return False
    return True


def _authorized(websocket: WebSocket) -> bool:
    if not settings.api_key:
        return True
    provided = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
    return provided == settings.api_key


@router.websocket("/{query_id}/stream")
async def stream_progress(websocket: WebSocket, query_id: UUID) -> None:
    """Stream pipeline progress events for a query as JSON messages."""
    if not _authorized(websocket):
        await websocket.close(code=4401, reason="Invalid or missing API key")
        return
    if not await _owns_the_run(websocket, query_id):
        await websocket.close(code=4404, reason="Query not found")
        return

    await websocket.accept()
    queue = hub.subscribe(query_id)
    try:
        # Replay so a client that connects mid-run sees the whole run.
        for event in hub.history(query_id):
            await websocket.send_json(event)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
            except TimeoutError:
                await websocket.send_json({"event": "heartbeat", "query_id": str(query_id)})
                continue

            await websocket.send_json(event)
            if event.get("event") == "status" and event.get("status") in _TERMINAL:
                break
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - a broken socket must not surface as a 500
        logger.debug("Progress stream closed for %s", query_id, exc_info=True)
    finally:
        hub.unsubscribe(query_id, queue)
        with contextlib.suppress(RuntimeError):
            await websocket.close()
