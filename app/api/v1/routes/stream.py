"""WebSocket progress streaming.

Kept in its own router because FastAPI's HTTP security dependencies (the
`X-API-Key` scheme used by every other route) cannot run on a WebSocket
handshake — auth is enforced inline here instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.events import hub
from app.models.query import QueryStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/queries", tags=["queries"])

_HEARTBEAT_SECONDS = 30.0
_TERMINAL = {str(QueryStatus.completed), str(QueryStatus.failed)}


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
