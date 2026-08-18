"""In-process progress pub/sub for WebSocket streaming (Phase 4, extended in v2).

v1 published coarse stage-completion events. v2 adds three fields to every
message so a frontend can drive a single stepper instead of special-casing
event names:

* ``seq``     — monotonic per query. A client that reconnects passes the last
                seq it saw and gets only what it missed; a gap in the sequence
                means the replay buffer or a slow-consumer queue dropped
                something and the client should refetch state over REST.
* ``phase``   — which pipeline stage the event belongs to, carried forward from
                the previous event when an event does not imply a new stage.
* ``progress`` — optional 0..1 fraction *within* the phase, present only where
                the publisher genuinely knows the denominator.

Single-process by design: the pipeline runs as an asyncio task inside the API
process, so an in-memory hub is sufficient and keeps the deployment free of a
broker. The cost is that history dies with the process and a second worker
cannot see the first worker's runs — run the API with one worker, or swap this
for Redis pub/sub plus a persisted event table.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Pipeline phases in the order the UI should present them.
PHASE_ORDER = (
    "queued",
    "structuring",
    "retrieving",
    "ranking",
    "storing",
    "processing",
    "clustering",
    "synthesizing",
    "completed",
    "failed",
)

_PHASE_BY_EVENT = {
    "pipeline_started": "queued",
    "query_structured": "structuring",
    "retrieval_started": "retrieving",
    "retrieval_endpoint": "retrieving",
    "papers_retrieved": "retrieving",
    "papers_ranked": "ranking",
    "paper_shortlisted": "ranking",
    "papers_stored": "storing",
    "paper_started": "processing",
    "paper_pdf": "processing",
    "paper_normalized": "processing",
    "paper_claims_extracted": "processing",
    "paper_claims_embedded": "processing",
    "paper_processed": "processing",
    "paper_failed": "processing",
    "extraction_complete": "processing",
    "clusters_formed": "clustering",
    "cluster_analyzed": "clustering",
    "clustering_complete": "clustering",
    "section_ready": "synthesizing",
    "report_ready": "synthesizing",
    "cancelled": "failed",
    "failed": "failed",
}

_PHASE_BY_STATUS = {
    "pending": "queued",
    "structuring": "structuring",
    "retrieving": "retrieving",
    "processing": "processing",
    "clustering": "clustering",
    "completed": "completed",
    "failed": "failed",
}


class ProgressCallback(Protocol):
    """How a service reports progress without importing the hub.

    Services take one of these so they stay decoupled from transport: the
    pipeline passes a callback bound to the running query, tests pass a list
    appender, and `scripts/` passes a printer.
    """

    def __call__(self, event: str, /, **payload: Any) -> None: ...


class ProgressHub:
    def __init__(self) -> None:
        self._subscribers: dict[UUID, set[asyncio.Queue]] = defaultdict(set)
        self._history: dict[UUID, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=settings.event_replay_max)
        )
        self._seq: dict[UUID, int] = defaultdict(int)
        self._phase: dict[UUID, str] = {}

    # ------------------------------------------------------------- publish

    def publish(
        self,
        query_id: UUID,
        event: str,
        *,
        phase: str | None = None,
        progress: float | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        resolved = self._resolve_phase(query_id, event, phase, payload)
        self._seq[query_id] += 1

        message: dict[str, Any] = {
            "query_id": str(query_id),
            "event": event,
            "seq": self._seq[query_id],
            "phase": resolved,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if progress is not None:
            message["progress"] = round(min(max(float(progress), 0.0), 1.0), 4)
        message.update(payload)

        self._history[query_id].append(message)
        for queue in list(self._subscribers.get(query_id, ())):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:  # pragma: no cover - slow consumer
                # The client sees the seq gap and can refetch over REST.
                logger.debug("Dropping progress event for slow subscriber on %s", query_id)
        return message

    def callback_for(self, query_id: UUID) -> ProgressCallback:
        """Bind a publisher to one query, for passing into services."""

        def emit(event: str, /, **payload: Any) -> None:
            self.publish(query_id, event, **payload)

        return emit

    def _resolve_phase(
        self,
        query_id: UUID,
        event: str,
        explicit: str | None,
        payload: dict[str, Any],
    ) -> str:
        if explicit:
            phase = explicit
        elif event == "status":
            phase = _PHASE_BY_STATUS.get(str(payload.get("status")), self._phase.get(query_id, ""))
        else:
            phase = _PHASE_BY_EVENT.get(event, "")
        if not phase:
            phase = self._phase.get(query_id, "queued")
        self._phase[query_id] = phase
        return phase

    # ------------------------------------------------------------- consume

    def history(self, query_id: UUID, since: int = 0) -> list[dict[str, Any]]:
        """Events recorded for a query, optionally only those after `since`."""
        events = self._history.get(query_id, ())
        if since <= 0:
            return list(events)
        return [event for event in events if int(event.get("seq", 0)) > since]

    def snapshot(self, query_id: UUID) -> dict[str, Any]:
        """Where a run has got to, for the opening frame of a new subscriber."""
        events = self._history.get(query_id, ())
        return {
            "last_seq": self._seq.get(query_id, 0),
            "phase": self._phase.get(query_id),
            "buffered": len(events),
            # A client asking for events older than this cannot be served from
            # memory — it must reload state over REST instead of replaying.
            "oldest_seq": int(events[0]["seq"]) if events else 0,
        }

    def subscribe(self, query_id: UUID) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=settings.event_queue_maxsize)
        self._subscribers[query_id].add(queue)
        return queue

    def unsubscribe(self, query_id: UUID, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(query_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(query_id, None)

    def subscriber_count(self, query_id: UUID) -> int:
        return len(self._subscribers.get(query_id, ()))

    def clear(self, query_id: UUID) -> None:
        self._history.pop(query_id, None)
        self._subscribers.pop(query_id, None)
        self._seq.pop(query_id, None)
        self._phase.pop(query_id, None)


hub = ProgressHub()
