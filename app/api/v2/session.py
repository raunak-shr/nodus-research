"""One WebSocket connection: dispatch, subscriptions, heartbeats.

Design points that matter:

* **Every write goes through a lock.** Request replies, forwarded progress
  events and heartbeats are produced by different tasks; concurrent
  `send_json` calls on one socket interleave and corrupt frames.
* **Requests run as tasks.** A slow action (a PDF render, `wait: true`) must not
  block progress events or the heartbeat, so each request is dispatched
  concurrently up to a per-connection ceiling.
* **Heartbeats never stop.** Whenever nothing has been sent for
  `WS_HEARTBEAT_SECONDS`, a heartbeat frame goes out — including after a run
  finishes — so proxies and load balancers cannot reap an idle connection.
* **Subscribe before replay.** A subscription attaches to the hub first, then
  replays history, then drops any live event already covered by the replay.
  Doing it the other way round loses events published in between.
* **Expensive actions are rate limited here.** The socket reaches the same
  services the REST routes do, so without this it would be a way around every
  per-caller limit those routes enforce. The bucket is chosen by the action's
  declared `cost`, and keyed on the peer address for the life of the connection.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import WebSocket
from pydantic import ValidationError

from app.api.v2.actions import REGISTRY, ActionContext
from app.core.config import settings
from app.core.events import hub
from app.schemas import stream as frames
from app.services import limits
from app.services.errors import BadRequest, NodusError, TooManyRequests

logger = logging.getLogger(__name__)

_MAX_INFLIGHT_REQUESTS = 8


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Subscription:
    """A live forward of one query's events onto this connection."""

    def __init__(self, query_id: UUID, queue: asyncio.Queue, pump: asyncio.Task) -> None:
        self.query_id = query_id
        self.queue = queue
        self.pump = pump

    async def close(self) -> None:
        self.pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.pump
        hub.unsubscribe(self.query_id, self.queue)


class Connection:
    def __init__(self, websocket: WebSocket, *, is_admin: bool = False) -> None:
        self.websocket = websocket
        self.is_admin = is_admin
        # Resolved once: the peer cannot change for the life of the socket.
        self._client_key = limits.client_key(
            client_host=websocket.client.host if websocket.client else None,
            forwarded_for=websocket.headers.get("x-forwarded-for"),
        )
        self._send_lock = asyncio.Lock()
        self._subscriptions: dict[UUID, Subscription] = {}
        self._requests: set[asyncio.Task] = set()
        self._closing = False
        self._last_send = time.monotonic()

    # ------------------------------------------------------------- sending

    async def send(self, frame: dict[str, Any]) -> None:
        if self._closing:
            return
        async with self._send_lock:
            await self.websocket.send_json(frame)
            self._last_send = time.monotonic()

    async def send_model(self, frame: Any) -> None:
        await self.send(frame.model_dump(mode="json"))

    async def send_error(
        self,
        error: NodusError,
        *,
        request_id: str | None = None,
        action: str | None = None,
    ) -> None:
        await self.send_model(
            frames.ErrorFrame(
                id=request_id,
                action=action,
                error=frames.ErrorBody(
                    code=error.code,
                    message=error.message,
                    detail={k: str(v) for k, v in error.detail.items()},
                ),
            )
        )

    # -------------------------------------------------------- subscriptions

    async def subscribe(self, query_id: UUID, since: int = 0) -> dict[str, Any]:
        """Attach to a query's event stream, replaying what the client missed."""
        existing = self._subscriptions.get(query_id)
        if existing:
            await existing.close()
            self._subscriptions.pop(query_id, None)

        queue = hub.subscribe(query_id)
        replay = hub.history(query_id, since=since)
        for event in replay:
            await self.send(self._event_frame(query_id, event))

        highest = max((int(e.get("seq", 0)) for e in replay), default=since)
        pump = asyncio.create_task(
            self._pump(query_id, queue, after_seq=highest),
            name=f"ws-pump:{query_id}",
        )
        self._subscriptions[query_id] = Subscription(query_id, queue, pump)

        snapshot = hub.snapshot(query_id)
        return {
            "subscribed": True,
            "query_id": str(query_id),
            "replayed": len(replay),
            "since": since,
            **snapshot,
        }

    def unsubscribe(self, query_id: UUID) -> bool:
        subscription = self._subscriptions.pop(query_id, None)
        if not subscription:
            return False
        asyncio.create_task(subscription.close())
        return True

    def subscriptions(self) -> list[str]:
        return [str(qid) for qid in self._subscriptions]

    def _event_frame(self, query_id: UUID, event: dict[str, Any]) -> dict[str, Any]:
        return {"type": "event", "topic": f"query:{query_id}", **event}

    async def _pump(self, query_id: UUID, queue: asyncio.Queue, *, after_seq: int) -> None:
        """Forward live events, skipping any already covered by the replay."""
        while True:
            event = await queue.get()
            if int(event.get("seq", 0)) <= after_seq:
                continue
            await self.send(self._event_frame(query_id, event))

    # ------------------------------------------------------------ dispatch

    async def handle_text(self, raw: str) -> None:
        try:
            request = frames.Request.model_validate_json(raw)
        except ValidationError as exc:
            await self.send_error(
                BadRequest("Malformed request frame", errors=exc.error_count()),
            )
            return

        entry = REGISTRY.get(request.action)
        if entry is None:
            await self.send_error(
                BadRequest(f"Unknown action: {request.action}"),
                request_id=request.id,
                action=request.action,
            )
            return

        if len(self._requests) >= _MAX_INFLIGHT_REQUESTS:
            await self.send_error(
                BadRequest(
                    "Too many requests in flight on this connection",
                    limit=_MAX_INFLIGHT_REQUESTS,
                ),
                request_id=request.id,
                action=request.action,
            )
            return

        # Before spawning the task, so a throttled caller costs nothing to turn
        # away. Reads carry no limiter and skip this entirely.
        limiter = limits.limiter_for_cost(entry.cost)
        if limiter is not None:
            try:
                limiter.check(self._client_key)
            except TooManyRequests as exc:
                await self.send_error(exc, request_id=request.id, action=request.action)
                return

        task = asyncio.create_task(self._run(entry, request), name=f"ws-action:{request.action}")
        self._requests.add(task)
        task.add_done_callback(self._requests.discard)

    async def _run(self, entry: Any, request: frames.Request) -> None:
        try:
            params = entry.params.model_validate(request.params)
        except ValidationError as exc:
            await self.send_error(
                BadRequest("Invalid params", errors=exc.errors(include_url=False)),
                request_id=request.id,
                action=request.action,
            )
            return

        try:
            data = await entry.handler(
                ActionContext(
                    connection=self, is_admin=self.is_admin, client_key=self._client_key
                ),
                params,
            )
        except NodusError as exc:
            await self.send_error(exc, request_id=request.id, action=request.action)
            return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - one failed action must not kill the socket
            logger.exception("Action %s failed", request.action)
            await self.send_model(
                frames.ErrorFrame(
                    id=request.id,
                    action=request.action,
                    error=frames.ErrorBody(
                        code="internal_error",
                        message="Action failed — see server logs",
                    ),
                )
            )
            return

        await self.send_model(
            frames.ResultFrame(id=request.id, action=request.action, data=data)
        )

    # ------------------------------------------------------------ lifecycle

    async def heartbeat_forever(self) -> None:
        """Keep the socket warm for as long as it is open.

        Only fires when the connection has been silent for a full interval —
        real traffic is its own keepalive, and duplicating it would just add
        noise to the client's message handler.
        """
        interval = max(1.0, settings.ws_heartbeat_seconds)
        while True:
            idle = time.monotonic() - self._last_send
            if idle < interval:
                await asyncio.sleep(interval - idle)
                continue
            await self.send_model(frames.HeartbeatFrame(ts=_now()))
            await asyncio.sleep(interval)

    async def aclose(self) -> None:
        self._closing = True
        for task in list(self._requests):
            task.cancel()
        if self._requests:
            await asyncio.gather(*list(self._requests), return_exceptions=True)
        for subscription in list(self._subscriptions.values()):
            await subscription.close()
        self._subscriptions.clear()
