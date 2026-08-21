"""v2 WebSocket protocol: frame envelopes and per-action parameter models.

The whole v2 surface is one socket, so this module is the contract that replaces
OpenAPI for it. `meta.describe` returns the JSON Schema of every model here,
which is what a frontend generates its client types from.

Frames, client → server:

    {"id": "7", "action": "queries.create", "params": {"query": "…"}}

Frames, server → client:

    {"type": "ready",     "protocol": "nodus.v2", …}      once, on connect
    {"type": "result",    "id": "7", "action": …, "data": …}
    {"type": "error",     "id": "7", "action": …, "error": {"code", "message", "detail"}}
    {"type": "event",     "topic": "query:<uuid>", "event": "paper_processed", …}
    {"type": "heartbeat", "ts": "…"}

`id` is echoed verbatim so a client can match replies to requests; it is null on
frames the server sends unprompted.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.chat import ChatTurn
from app.schemas.cluster import ClusterUpdate
from app.schemas.report import ReportUpdate, SectionNarrativeUpdate

PROTOCOL_VERSION = "nodus.v2"


# --------------------------------------------------------------- envelopes


class Request(BaseModel):
    """One client request."""

    id: str | None = Field(default=None, description="Echoed on the matching reply")
    action: str = Field(description="Action name, e.g. 'queries.create'")
    params: dict[str, Any] = Field(default_factory=dict)


class ErrorBody(BaseModel):
    code: str = Field(description="Stable identifier: bad_request, not_found, conflict, …")
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ErrorFrame(BaseModel):
    type: Literal["error"] = "error"
    id: str | None = None
    action: str | None = None
    error: ErrorBody


class ResultFrame(BaseModel):
    type: Literal["result"] = "result"
    id: str | None = None
    action: str
    data: Any = None


class EventFrame(BaseModel):
    """A pipeline progress event, forwarded from the in-process hub.

    Carries the hub's fields — `event`, `seq`, `phase`, `timestamp`, an optional
    `progress` fraction, plus event-specific keys. A gap in `seq` means events
    were dropped (slow consumer or replay buffer overflow): reload state with
    `queries.get` / `queries.stats` rather than assuming continuity.
    """

    model_config = {"extra": "allow"}

    type: Literal["event"] = "event"
    topic: str = Field(description="'query:<uuid>'")
    event: str
    seq: int
    phase: str
    timestamp: str


class ReadyFrame(BaseModel):
    type: Literal["ready"] = "ready"
    protocol: str = PROTOCOL_VERSION
    heartbeat_seconds: float
    actions: list[str]
    resumed_subscriptions: list[str] = Field(default_factory=list)
    #: Whose history this connection reads — the resolved owner key, echoed so a
    #: client can see whether the token it sent arrived (`t:…`) or whether it is
    #: falling back to its address (`a:…`), which is shared with anything else on
    #: that address. Not a credential: it is the identity the caller supplied.
    owner: str = ""


class HeartbeatFrame(BaseModel):
    """Idle keepalive. Sent whenever there is nothing else to send, so proxies
    and load balancers do not reap the connection."""

    type: Literal["heartbeat"] = "heartbeat"
    ts: str


# ------------------------------------------------------------ action params


class Empty(BaseModel):
    pass


class Page(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class QueryRef(BaseModel):
    query_id: UUID


class CreateQuery(BaseModel):
    query: str = Field(min_length=3, description="The research question")
    subscribe: bool = Field(
        default=True,
        description="Stream this run's progress on this connection (recommended)",
    )
    wait: bool = Field(
        default=False,
        description="Admin only. Reply only when the whole pipeline finishes. "
        "Minutes — prefer subscribing.",
    )


class InterpretQuery(BaseModel):
    query: str = Field(min_length=3, description="A draft research question to assess")


class Subscribe(BaseModel):
    query_id: UUID
    since: int = Field(
        default=0,
        ge=0,
        description="Last seq already seen; 0 replays everything still buffered",
    )


class Events(BaseModel):
    query_id: UUID
    since: int = Field(default=0, ge=0)


class PapersForQuery(Page):
    query_id: UUID


class PaperRef(BaseModel):
    paper_id: UUID


class ClaimsForPaper(Page):
    paper_id: UUID


class ClaimRef(BaseModel):
    claim_id: UUID


class ClusterRef(BaseModel):
    cluster_id: UUID


class ClusterPatch(BaseModel):
    cluster_id: UUID
    patch: ClusterUpdate


class ClusterClaimRef(BaseModel):
    cluster_id: UUID
    claim_id: UUID


class ClusterStance(ClusterClaimRef):
    stance: Literal["supports", "contradicts", "neutral"]


class ReportPatch(BaseModel):
    query_id: UUID
    patch: ReportUpdate


class SectionPatch(BaseModel):
    query_id: UUID
    cluster_id: UUID
    patch: SectionNarrativeUpdate


class RenderReport(BaseModel):
    query_id: UUID
    variant: Literal["screen", "print"] = "screen"


class ExportReport(BaseModel):
    query_id: UUID
    format: Literal["markdown", "json", "html"] = "markdown"


class AskReport(BaseModel):
    """A question about one query's finished report.

    `history` is the thread so far, sent by the client on every question: this
    action stores nothing, so the socket has no chat state to lose on a
    reconnect and two readers of the same report never see each other's turns.
    """

    query_id: UUID
    question: str = Field(min_length=3, max_length=600)
    history: list[ChatTurn] = Field(
        default_factory=list,
        max_length=40,
        description="Earlier turns, oldest first. Only the last few are shown to the model.",
    )


class FollowUp(BaseModel):
    query_id: UUID
    query: str = Field(min_length=3)
    subscribe: bool = True
    wait: bool = Field(default=False, description="Admin only. See CreateQuery.wait.")
