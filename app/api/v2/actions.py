"""v2 action registry — the whole API surface, addressed by name over one socket.

Each action declares a Pydantic params model, so a malformed request fails with
a validation error frame instead of an exception, and `meta.describe` can hand
the frontend a machine-readable schema for every call (the socket has no
OpenAPI document).

Handlers open their own database session: a WebSocket connection is long-lived
and must not hold one open between requests.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.events import PHASE_ORDER, hub
from app.core.llm_provider import get_embedder_name, get_llm_name
from app.db.session import AsyncSessionLocal, pool_warning
from app.models.claim import Claim
from app.models.cluster import ClaimCluster
from app.models.paper import NormalizedPaper, Paper, QueryPaper
from app.models.query import Query, QueryStatus
from app.schemas import stream as frames
from app.schemas.claim import ClaimRead
from app.schemas.cluster import ClaimClusterRead
from app.schemas.paper import NormalizedPaperRead, PaperRead
from app.schemas.query import QueryRead, QueryWithPapersRead
from app.schemas.report import ReportRead
from app.services import (
    cluster_edit,
    export,
    limits,
    ownership,
    paper_listing,
    pdf_export,
    provenance,
    query_assessor,
    report_chat,
    report_edit,
    report_render,
    runner,
    synthesizer,
    uploads,
)
from app.services import graph as graph_service
from app.services.errors import BadRequest, Forbidden, NotFound


class Subscriber(Protocol):
    """The parts of a connection an action is allowed to touch."""

    async def subscribe(self, query_id: UUID, since: int = 0) -> dict[str, Any]: ...

    def unsubscribe(self, query_id: UUID) -> bool: ...

    def subscriptions(self) -> list[str]: ...


@dataclass
class ActionContext:
    connection: Subscriber
    #: Whether the handshake presented ADMIN_API_KEY. Gates the inline `wait`
    #: path, which is otherwise a cheap way to pin a database session.
    is_admin: bool = False
    #: The identity this connection's rate limits are keyed on, resolved once at
    #: the handshake. An action that reports budgets must read the same key the
    #: limiter charges, or it would report someone else's allowance.
    client_key: str = "unknown"
    #: Whose history this connection sees. Resolved once at the handshake from
    #: the owner token, falling back to the client address — see
    #: `app/services/ownership.py`. Every query is stamped with it, and anything
    #: reached through a query or a cluster id is refused to anyone else.
    owner_key: str = "a:unknown"


Handler = Callable[[ActionContext, Any], Awaitable[Any]]


@dataclass(frozen=True)
class Action:
    name: str
    handler: Handler
    params: type[BaseModel]
    summary: str
    #: What this action costs, which decides how it is rate limited: "run" (a
    #: pipeline or a resynthesis), "edit" (a database write) or "read". Reads
    #: are not limited — see `app/services/limits.py`.
    cost: str = "read"


REGISTRY: dict[str, Action] = {}

# base64 inflates by ~33%; a report PDF is a few hundred KB, so this ceiling
# only trips on something pathological — better a clear error than a dead socket.
_MAX_PDF_FRAME_BYTES = 32 * 1024 * 1024


def action(name: str, params: type[BaseModel], summary: str, cost: str = "read"):
    def register(fn: Handler) -> Handler:
        REGISTRY[name] = Action(name=name, handler=fn, params=params, summary=summary, cost=cost)
        return fn

    return register


def _require_admin_for_wait(wait: bool, is_admin: bool) -> None:
    """`wait` runs the pipeline inline, holding this request open for minutes.

    Admin-only for the same reason as on the REST surface: it pins resources for
    the length of a whole run, and subscribing to the stream is strictly better.
    """
    if wait and not is_admin:
        raise Forbidden(
            "wait is admin-only — subscribe to this query's progress instead",
            hint="queries.subscribe",
        )


def _dump(model: BaseModel) -> dict[str, Any]:
    """JSON-safe serialization — UUIDs and datetimes must survive the wire."""
    return model.model_dump(mode="json")


async def _require_query(ctx: ActionContext, query_id: UUID, db: AsyncSession) -> Query:
    """The query, if it is this caller's to read.

    Every query-scoped action goes through here rather than loading the row
    itself: "no such query" and "not your query" have to be the same answer, or
    the difference between them enumerates other people's runs.
    """
    return await ownership.require_query(query_id, db, owner=ctx.owner_key, is_admin=ctx.is_admin)


async def _require_cluster(ctx: ActionContext, cluster_id: UUID, db: AsyncSession) -> None:
    """Refuse a cluster whose query belongs to someone else.

    Clusters are per-query, so this is the query check reached through
    `cluster.query_id` — the same rule, not a second one.
    """
    await ownership.require_cluster(cluster_id, db, owner=ctx.owner_key, is_admin=ctx.is_admin)


# ------------------------------------------------------------------- meta


@action("meta.describe", frames.Empty, "Every action with its JSON Schema — for codegen")
async def meta_describe(ctx: ActionContext, params: frames.Empty) -> dict[str, Any]:
    return {
        "protocol": frames.PROTOCOL_VERSION,
        "heartbeat_seconds": settings.ws_heartbeat_seconds,
        "phases": list(PHASE_ORDER),
        "actions": [
            {
                "name": item.name,
                "summary": item.summary,
                "cost": item.cost,
                "params": item.params.model_json_schema(),
            }
            for item in sorted(REGISTRY.values(), key=lambda a: a.name)
        ],
    }


@action("meta.health", frames.Empty, "Liveness check")
async def meta_health(ctx: ActionContext, params: frames.Empty) -> dict[str, Any]:
    return {"status": "ok", "version": "2.0.0"}


@action("meta.limits", frames.Empty, "This connection's admission state and rate budgets")
async def meta_limits(ctx: ActionContext, params: frames.Empty) -> dict[str, Any]:
    return limits.snapshot_for(ctx.client_key)


@action("meta.config", frames.Empty, "Non-secret view of the active configuration")
async def meta_config(ctx: ActionContext, params: frames.Empty) -> dict[str, Any]:
    return {
        "llm_provider": settings.llm_provider,
        "llm_model": get_llm_name(),
        "embedding_provider": settings.embedding_provider,
        "embedding_model": get_embedder_name(),
        "embedding_dim": settings.embedding_dim,
        "db_pool_warning": pool_warning,
        "auth_enabled": bool(settings.api_key),
        "max_concurrent_papers": settings.max_concurrent_papers,
        "top_k_papers": settings.top_k_papers,
        "cluster_similarity_threshold": settings.active_cluster_threshold,
        "retrieval_mode": settings.retrieval_mode,
        "pdf_enabled": settings.pdf_enabled,
        # The upload ceilings, so the drop zone can refuse an oversized file
        # before sending it rather than after — the numbers live in one place
        # and the client reads them rather than hardcoding a second copy.
        "uploads_enabled": settings.uploads_enabled,
        # How much of any paper is read — retrieved or uploaded, the same
        # budget. The drop zone quotes it, so it must not be a second copy of
        # the number living in the client.
        "max_pages_read": settings.pdf_max_pages,
        "upload_max_bytes": settings.upload_max_bytes,
        "upload_max_pages": settings.upload_max_pages,
        "upload_max_papers": settings.upload_max_papers,
        "upload_min_papers": settings.upload_min_papers,
        "admin_enabled": bool(settings.admin_api_key),
        "rate_limit_enabled": settings.rate_limit_enabled,
        "runs": limits.run_gate.snapshot(),
    }


# ---------------------------------------------------------------- queries


@action(
    "queries.create",
    frames.CreateQuery,
    "Submit a research question and start the pipeline",
    cost="run",
)
async def queries_create(ctx: ActionContext, params: frames.CreateQuery) -> dict[str, Any]:
    _require_admin_for_wait(params.wait, ctx.is_admin)

    uploaded = [str(pid) for pid in params.paper_ids]
    if uploaded:
        # Checked before a slot is reserved and before the row is written: a
        # corpus that is too small, too large, or not the caller's uploads at
        # all is a mistake to report now, not a run to start and abandon.
        async with AsyncSessionLocal() as db:
            await uploads.resolve_for_run(uploaded, db)

    # The slot is reserved before the row is written, so a run refused for
    # capacity does not leave a `pending` query nothing will ever pick up.
    async with runner.admission() as reserved:
        async with AsyncSessionLocal() as db:
            query = Query(
                raw_query=params.query,
                status=QueryStatus.pending,
                owner_key=ctx.owner_key,
            )
            db.add(query)
            await db.commit()
            await db.refresh(query)
            payload = _dump(QueryRead.model_validate(query))
            query_id = query.id

        # Subscribe before launching so no event can land in the gap.
        subscription = None
        if params.subscribe:
            subscription = await ctx.connection.subscribe(query_id)

        if params.wait:
            from app.services.pipeline import run_pipeline_safe

            await run_pipeline_safe(query_id, params.query, uploaded_paper_ids=uploaded)
            async with AsyncSessionLocal() as db:
                query = await _require_query(ctx, query_id, db)
                payload = _dump(QueryRead.model_validate(query))
        else:
            reserved.launch(query_id, params.query, uploaded_paper_ids=uploaded)

    # Reported back rather than left to be inferred: the run screen has to know
    # there will be no retrieval phase before the first paper event arrives.
    return {"query": payload, "subscription": subscription, "uploaded_corpus": bool(uploaded)}


@action(
    "queries.interpret",
    frames.InterpretQuery,
    "Read a draft question back and say whether it is worth running",
    cost="interpret",
)
async def queries_interpret(ctx: ActionContext, params: frames.InterpretQuery) -> dict[str, Any]:
    """Pre-submission only: nothing is stored and no run is started.

    A verdict other than `ready` is advice. `queries.create` still accepts the
    question exactly as typed — the point is that the caller knows first.
    """
    return _dump(await query_assessor.interpret(params.query))


@action("queries.list", frames.Page, "List this caller's queries, newest first")
async def queries_list(ctx: ActionContext, params: frames.Page) -> list[dict[str, Any]]:
    """One caller's history, not the deployment's.

    Scoped on `owner_key`, which is why the index behind it is
    `(owner_key, created_at DESC)`. The admin key sees everything, including the
    rows written before ownership existed.
    """
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                ownership.scope(select(Query), ctx.owner_key, is_admin=ctx.is_admin)
                .order_by(Query.created_at.desc())
                .limit(params.limit)
                .offset(params.offset)
            )
        ).scalars()
        return [_dump(QueryRead.model_validate(q)) for q in rows.all()]


@action("queries.get", frames.QueryRef, "Query status with its ranked papers")
async def queries_get(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        query = await _require_query(ctx, params.query_id, db)
        query_papers = (
            (
                await db.execute(
                    select(QueryPaper)
                    .where(QueryPaper.query_id == params.query_id)
                    .options(
                        # Normalisation travels with the paper rather than being
                        # fetched per row afterwards. A client that asked once
                        # per paper needed twenty round trips for a twenty-paper
                        # query, which is over the socket's in-flight ceiling —
                        # so the tail was refused and read as failed papers.
                        selectinload(QueryPaper.paper).selectinload(Paper.normalized_paper)
                    )
                    .order_by(QueryPaper.rank)
                )
            )
            .scalars()
            .all()
        )
        payload = QueryWithPapersRead(
            id=query.id,
            raw_query=query.raw_query,
            structured_query=query.structured_query,
            status=query.status,
            paper_count=query.paper_count,
            error_message=query.error_message,
            parent_query_id=query.parent_query_id,
            created_at=query.created_at,
            updated_at=query.updated_at,
            papers=await paper_listing.read_query_papers(query_papers, db),
        )
        data = _dump(payload)
        data["running"] = runner.is_running(params.query_id)
        return data


@action("queries.stats", frames.QueryRef, "Counts across the pipeline for one query")
async def queries_stats(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        query = await _require_query(ctx, params.query_id, db)
        claim_count = (
            await db.execute(
                select(func.count(Claim.id))
                .join(QueryPaper, QueryPaper.paper_id == Claim.paper_id)
                .where(QueryPaper.query_id == params.query_id)
            )
        ).scalar_one()
        cluster_count = (
            await db.execute(
                select(func.count(ClaimCluster.id)).where(ClaimCluster.query_id == params.query_id)
            )
        ).scalar_one()
        report = await synthesizer.load_report(params.query_id, db)
        return {
            "query_id": str(params.query_id),
            "status": str(query.status),
            "running": runner.is_running(params.query_id),
            "paper_count": query.paper_count,
            "claim_count": claim_count,
            "cluster_count": cluster_count,
            "report_sections": len(report.sections or []) if report else 0,
            **hub.snapshot(params.query_id),
        }


@action(
    "queries.delete",
    frames.QueryRef,
    "Delete a query and everything derived from it",
    cost="edit",
)
async def queries_delete(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    runner.cancel(params.query_id)
    async with AsyncSessionLocal() as db:
        query = await _require_query(ctx, params.query_id, db)
        await db.delete(query)
        await db.commit()
    ctx.connection.unsubscribe(params.query_id)
    hub.clear(params.query_id)
    return {"deleted": True, "query_id": str(params.query_id)}


@action("queries.cancel", frames.QueryRef, "Cancel an in-flight pipeline run")
async def queries_cancel(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    # Checked against the database rather than the run registry: cancelling
    # somebody else's run is the one write that needs no id but the query's.
    async with AsyncSessionLocal() as db:
        await _require_query(ctx, params.query_id, db)
    cancelled = runner.cancel(params.query_id)
    return {"cancelled": cancelled, "query_id": str(params.query_id)}


@action("queries.subscribe", frames.Subscribe, "Stream a query's progress on this connection")
async def queries_subscribe(ctx: ActionContext, params: frames.Subscribe) -> dict[str, Any]:
    # A stream is a read of someone's run in progress, so it is scoped like any
    # other. Without this, a query id would be enough to watch it live.
    async with AsyncSessionLocal() as db:
        await _require_query(ctx, params.query_id, db)
    return await ctx.connection.subscribe(params.query_id, since=params.since)


@action("queries.unsubscribe", frames.QueryRef, "Stop streaming a query on this connection")
async def queries_unsubscribe(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    return {
        "subscribed": False,
        "was_subscribed": ctx.connection.unsubscribe(params.query_id),
        "query_id": str(params.query_id),
    }


@action("queries.events", frames.Events, "Replay buffered progress events (gap recovery)")
async def queries_events(ctx: ActionContext, params: frames.Events) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        query = await _require_query(ctx, params.query_id, db)
        return {
            "query_id": str(params.query_id),
            "status": str(query.status),
            "error_message": query.error_message,
            "events": hub.history(params.query_id, since=params.since),
            **hub.snapshot(params.query_id),
        }


@action(
    "queries.followup",
    frames.FollowUp,
    "Ask a follow-up scoped to a previous query",
    cost="run",
)
async def queries_followup(ctx: ActionContext, params: frames.FollowUp) -> dict[str, Any]:
    _require_admin_for_wait(params.wait, ctx.is_admin)

    async with runner.admission() as reserved:
        async with AsyncSessionLocal() as db:
            parent = await _require_query(ctx, params.query_id, db)
            combined = f"{parent.raw_query} — follow-up: {params.query}"
            child = Query(
                raw_query=params.query,
                status=QueryStatus.pending,
                parent_query_id=parent.id,
                # The child is the same reader's, so it inherits the owner
                # rather than the connection's — an admin asking a follow-up on
                # someone's run must not take the run away from them.
                owner_key=parent.owner_key or ctx.owner_key,
            )
            db.add(child)
            await db.commit()
            await db.refresh(child)
            payload = _dump(QueryRead.model_validate(child))
            child_id = child.id

        subscription = None
        if params.subscribe:
            subscription = await ctx.connection.subscribe(child_id)

        if params.wait:
            from app.services.pipeline import run_pipeline_safe

            await run_pipeline_safe(child_id, combined)
            async with AsyncSessionLocal() as db:
                child = await _require_query(ctx, child_id, db)
                payload = _dump(QueryRead.model_validate(child))
        else:
            reserved.launch(child_id, combined)

    return {"query": payload, "subscription": subscription}


@action("queries.followups", frames.QueryRef, "List follow-ups of a query")
async def queries_followups(ctx: ActionContext, params: frames.QueryRef) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        await _require_query(ctx, params.query_id, db)
        rows = (
            await db.execute(
                select(Query)
                .where(Query.parent_query_id == params.query_id)
                .order_by(Query.created_at)
            )
        ).scalars()
        return [_dump(QueryRead.model_validate(q)) for q in rows.all()]


# ----------------------------------------------------------------- papers
#
# Papers and claims are the global cache — one paper normalised once is reused by
# every query that retrieves it — so they carry no owner and these reads are not
# scoped. What is scoped is anything that reveals *which question* someone asked:
# a paper's row says nothing about that, while `papers.list` for a query id says
# all of it, and is checked accordingly.


@action("papers.list", frames.PapersForQuery, "Ranked papers retrieved for a query")
async def papers_list(ctx: ActionContext, params: frames.PapersForQuery) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        await _require_query(ctx, params.query_id, db)
        rows = (
            await db.execute(
                select(QueryPaper)
                .where(QueryPaper.query_id == params.query_id)
                .options(selectinload(QueryPaper.paper).selectinload(Paper.normalized_paper))
                .order_by(QueryPaper.rank)
                .limit(params.limit)
                .offset(params.offset)
            )
        ).scalars()
        return [_dump(read) for read in await paper_listing.read_query_papers(list(rows.all()), db)]


@action(
    "papers.upload",
    frames.UploadPaper,
    "Hand over one PDF to run a query against, instead of searching",
    cost="upload",
)
async def papers_upload(ctx: ActionContext, params: frames.UploadPaper) -> dict[str, Any]:
    """Accept one PDF and store it as a paper, ready to be named in a run.

    Two steps rather than one, because the reader chooses the corpus in two:
    files are validated as they are dropped, and the run is started afterwards
    from the ids of the ones that were accepted. A file that never gets used
    costs a row in the global paper cache and nothing else — and re-uploading
    it later resolves to the same row, because the id is the hash of its bytes.
    """
    try:
        data = base64.b64decode(params.content_base64, validate=True)
    except Exception as exc:  # noqa: BLE001 - a malformed body is the caller's
        raise BadRequest("The file body is not valid base64.", filename=params.filename) from exc

    async with AsyncSessionLocal() as db:
        accepted = await uploads.accept_upload(params.filename, data, db)

    return {
        "paper_id": accepted.paper_id,
        "fingerprint": accepted.fingerprint,
        "filename": accepted.filename,
        "title": accepted.title,
        "authors": accepted.authors,
        "year": accepted.year,
        "pages": accepted.pages,
        # What was declared and what was read. They differ for a paper longer
        # than `pdf_max_pages`, and the caller says so rather than implying the
        # whole thing was taken in.
        "pages_read": accepted.pages_read,
        "characters": accepted.characters,
        # True when this exact file was already stored. The reader dropped it
        # twice, or dropped it again after a reload; either way it is one paper.
        "reused": accepted.reused,
    }


@action("papers.get", frames.PaperRef, "One paper's metadata")
async def papers_get(ctx: ActionContext, params: frames.PaperRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        paper = (
            await db.execute(select(Paper).where(Paper.id == params.paper_id))
        ).scalar_one_or_none()
        if not paper:
            raise NotFound("Paper not found", paper_id=str(params.paper_id))
        return _dump(PaperRead.model_validate(paper))


@action("papers.normalized", frames.PaperRef, "Study type and methodology for a paper")
async def papers_normalized(ctx: ActionContext, params: frames.PaperRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        record = (
            await db.execute(
                select(NormalizedPaper).where(NormalizedPaper.paper_id == params.paper_id)
            )
        ).scalar_one_or_none()
        if not record:
            raise NotFound("Paper has not been normalized", paper_id=str(params.paper_id))
        return _dump(NormalizedPaperRead.model_validate(record))


# --------------------------------------------------------- claims/clusters


@action("claims.list", frames.ClaimsForPaper, "Extracted claims for a paper")
async def claims_list(ctx: ActionContext, params: frames.ClaimsForPaper) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Claim)
                .where(Claim.paper_id == params.paper_id)
                .order_by(Claim.position_in_paper)
                .limit(params.limit)
                .offset(params.offset)
            )
        ).scalars()
        return [_dump(ClaimRead.model_validate(c)) for c in rows.all()]


@action(
    "claims.source",
    frames.ClaimRef,
    "The passage a claim was extracted from, with the quote located in it",
)
async def claims_source(ctx: ActionContext, params: frames.ClaimRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return _dump(await provenance.load_claim_source(params.claim_id, db))


@action("graph.get", frames.QueryRef, "One run as a graph: clusters, papers, authors, lineage")
async def graph_get(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    """Everything the Graph screen draws, in one frame.

    Four views over the same run, so one read rather than four — and emphatically
    not one read per cluster: a fan-out sized by the corpus is what the paper
    list already had to stop doing when the socket's in-flight ceiling started
    refusing its tail.
    """
    async with AsyncSessionLocal() as db:
        query = await _require_query(ctx, params.query_id, db)
        return _dump(await graph_service.build_graph(query, db))


@action("clusters.list", frames.QueryRef, "Clusters for a query, best evidence first")
async def clusters_list(ctx: ActionContext, params: frames.QueryRef) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        await _require_query(ctx, params.query_id, db)
        clusters = await cluster_edit.list_for_query(params.query_id, db)
        return [_dump(ClaimClusterRead.model_validate(c)) for c in clusters]


@action("clusters.get", frames.ClusterRef, "A cluster with its member claims and stances")
async def clusters_get(ctx: ActionContext, params: frames.ClusterRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await _require_cluster(ctx, params.cluster_id, db)
        return _dump(await cluster_edit.get_detail(params.cluster_id, db))


@action(
    "clusters.update",
    frames.ClusterPatch,
    "Override theme, summary, tier or drivers",
    cost="edit",
)
async def clusters_update(ctx: ActionContext, params: frames.ClusterPatch) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await _require_cluster(ctx, params.cluster_id, db)
        return _dump(await cluster_edit.update_cluster(params.cluster_id, params.patch, db))


@action(
    "clusters.set_stance",
    frames.ClusterStance,
    "Correct a claim's stance in a cluster",
    cost="edit",
)
async def clusters_set_stance(ctx: ActionContext, params: frames.ClusterStance) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await _require_cluster(ctx, params.cluster_id, db)
        return _dump(
            await cluster_edit.set_stance(params.cluster_id, params.claim_id, params.stance, db)
        )


@action("clusters.add_claim", frames.ClusterStance, "Move a claim into a cluster", cost="edit")
async def clusters_add_claim(ctx: ActionContext, params: frames.ClusterStance) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await _require_cluster(ctx, params.cluster_id, db)
        return _dump(
            await cluster_edit.add_claim(params.cluster_id, params.claim_id, params.stance, db)
        )


@action("clusters.remove_claim", frames.ClusterClaimRef, "Drop a claim from a cluster", cost="edit")
async def clusters_remove_claim(
    ctx: ActionContext, params: frames.ClusterClaimRef
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await _require_cluster(ctx, params.cluster_id, db)
        await cluster_edit.remove_claim(params.cluster_id, params.claim_id, db)
        return {"removed": True, "claim_id": str(params.claim_id)}


# ----------------------------------------------------------------- report


@action("report.get", frames.QueryRef, "The synthesized three-axis report")
async def report_get(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await _require_query(ctx, params.query_id, db)
        report = await report_edit.require_report(params.query_id, db)
        return _dump(ReportRead.model_validate(report))


@action(
    "report.regenerate",
    frames.QueryRef,
    "Rebuild the report from current clusters",
    cost="run",
)
async def report_regenerate(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        query = await _require_query(ctx, params.query_id, db)
        report = await report_edit.regenerate(query, db)
        return _dump(ReportRead.model_validate(report))


@action(
    "report.refresh_sources",
    frames.QueryRef,
    "Re-read the claim rows behind each section, keeping the prose",
    cost="edit",
)
async def report_refresh_sources(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await _require_query(ctx, params.query_id, db)
        report = await report_edit.refresh_sources(params.query_id, db)
        return _dump(ReportRead.model_validate(report))


@action("report.update", frames.ReportPatch, "Edit report front matter or sections", cost="edit")
async def report_update(ctx: ActionContext, params: frames.ReportPatch) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await _require_query(ctx, params.query_id, db)
        report = await report_edit.update(params.query_id, params.patch, db)
        return _dump(ReportRead.model_validate(report))


@action(
    "report.section.update",
    frames.SectionPatch,
    "Edit one section's prose in place",
    cost="edit",
)
async def report_section_update(ctx: ActionContext, params: frames.SectionPatch) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await _require_query(ctx, params.query_id, db)
        report = await report_edit.update_section(
            params.query_id, params.cluster_id, params.patch, db
        )
        return _dump(ReportRead.model_validate(report))


@action("report.render", frames.RenderReport, "Rendered report HTML (screen or print variant)")
async def report_render_action(ctx: ActionContext, params: frames.RenderReport) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        query = await _require_query(ctx, params.query_id, db)
        report = await report_edit.require_report(params.query_id, db)
        html = report_render.render_report_html(report, query, variant=params.variant)
        return {
            "variant": params.variant,
            "title": report.title,
            "bytes": len(html.encode("utf-8")),
            "html": html,
        }


@action("report.export", frames.ExportReport, "Report as markdown, JSON or print-ready HTML")
async def report_export(ctx: ActionContext, params: frames.ExportReport) -> dict[str, Any]:
    renderers = {
        "markdown": (export.to_markdown, "text/markdown", "md"),
        "json": (export.to_json, "application/json", "json"),
        "html": (export.to_html, "text/html", "html"),
    }
    render, media_type, suffix = renderers[params.format]

    async with AsyncSessionLocal() as db:
        query = await _require_query(ctx, params.query_id, db)
        report = await report_edit.require_report(params.query_id, db)
        content = render(report, query)

    return {
        "format": params.format,
        "media_type": media_type,
        "filename": f"nodus-{str(params.query_id)[:8]}.{suffix}",
        "encoding": "utf-8",
        "content": content,
    }


@action(
    "chat.ask",
    frames.AskReport,
    "Ask a question about one query's report, answered from it alone",
    cost="chat",
)
async def chat_ask(ctx: ActionContext, params: frames.AskReport) -> dict[str, Any]:
    """Grounded in this query's report and clusters, and in nothing else.

    Not a retrieval path: no paper is fetched and no claim is re-extracted, so a
    question the report does not cover comes back `covered: false` rather than
    answered from the model's own recall. Asking something the report cannot
    settle is what `queries.followup` is for — a run, with a run's cost.
    """
    async with AsyncSessionLocal() as db:
        await _require_query(ctx, params.query_id, db)
        answer = await report_chat.answer(params.query_id, params.question, params.history, db)
        return _dump(answer)


@action("report.pdf", frames.QueryRef, "Report as a PDF, base64-encoded for download")
async def report_pdf(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        query = await _require_query(ctx, params.query_id, db)
        report = await report_edit.require_report(params.query_id, db)
        payload = await pdf_export.render_pdf(report, query)

    if len(payload) > _MAX_PDF_FRAME_BYTES:
        raise BadRequest(
            "PDF is too large to send in a single frame",
            bytes=len(payload),
            limit=_MAX_PDF_FRAME_BYTES,
        )

    return {
        "media_type": "application/pdf",
        "filename": pdf_export.filename_for(query),
        "encoding": "base64",
        "bytes": len(payload),
        "content": base64.b64encode(payload).decode("ascii"),
    }
