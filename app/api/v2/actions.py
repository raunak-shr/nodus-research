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
from app.schemas.paper import NormalizedPaperRead, PaperRead, QueryPaperRead
from app.schemas.query import QueryRead, QueryWithPapersRead
from app.schemas.report import ReportRead
from app.services import (
    cluster_edit,
    export,
    limits,
    pdf_export,
    provenance,
    query_assessor,
    report_chat,
    report_edit,
    report_render,
    runner,
    synthesizer,
)
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


async def _require_query(query_id: UUID, db: AsyncSession) -> Query:
    query = (await db.execute(select(Query).where(Query.id == query_id))).scalar_one_or_none()
    if not query:
        raise NotFound("Query not found", query_id=str(query_id))
    return query


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

    # The slot is reserved before the row is written, so a run refused for
    # capacity does not leave a `pending` query nothing will ever pick up.
    async with runner.admission() as reserved:
        async with AsyncSessionLocal() as db:
            query = Query(raw_query=params.query, status=QueryStatus.pending)
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

            await run_pipeline_safe(query_id, params.query)
            async with AsyncSessionLocal() as db:
                query = await _require_query(query_id, db)
                payload = _dump(QueryRead.model_validate(query))
        else:
            reserved.launch(query_id, params.query)

    return {"query": payload, "subscription": subscription}


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


@action("queries.list", frames.Page, "List queries, newest first")
async def queries_list(ctx: ActionContext, params: frames.Page) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Query)
                .order_by(Query.created_at.desc())
                .limit(params.limit)
                .offset(params.offset)
            )
        ).scalars()
        return [_dump(QueryRead.model_validate(q)) for q in rows.all()]


@action("queries.get", frames.QueryRef, "Query status with its ranked papers")
async def queries_get(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        query = await _require_query(params.query_id, db)
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
            papers=[QueryPaperRead.from_query_paper(qp) for qp in query_papers],
        )
        data = _dump(payload)
        data["running"] = runner.is_running(params.query_id)
        return data


@action("queries.stats", frames.QueryRef, "Counts across the pipeline for one query")
async def queries_stats(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        query = await _require_query(params.query_id, db)
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
        query = await _require_query(params.query_id, db)
        await db.delete(query)
        await db.commit()
    ctx.connection.unsubscribe(params.query_id)
    hub.clear(params.query_id)
    return {"deleted": True, "query_id": str(params.query_id)}


@action("queries.cancel", frames.QueryRef, "Cancel an in-flight pipeline run")
async def queries_cancel(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    cancelled = runner.cancel(params.query_id)
    return {"cancelled": cancelled, "query_id": str(params.query_id)}


@action("queries.subscribe", frames.Subscribe, "Stream a query's progress on this connection")
async def queries_subscribe(ctx: ActionContext, params: frames.Subscribe) -> dict[str, Any]:
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
        query = await _require_query(params.query_id, db)
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
            parent = await _require_query(params.query_id, db)
            combined = f"{parent.raw_query} — follow-up: {params.query}"
            child = Query(
                raw_query=params.query,
                status=QueryStatus.pending,
                parent_query_id=parent.id,
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
                child = await _require_query(child_id, db)
                payload = _dump(QueryRead.model_validate(child))
        else:
            reserved.launch(child_id, combined)

    return {"query": payload, "subscription": subscription}


@action("queries.followups", frames.QueryRef, "List follow-ups of a query")
async def queries_followups(ctx: ActionContext, params: frames.QueryRef) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        await _require_query(params.query_id, db)
        rows = (
            await db.execute(
                select(Query)
                .where(Query.parent_query_id == params.query_id)
                .order_by(Query.created_at)
            )
        ).scalars()
        return [_dump(QueryRead.model_validate(q)) for q in rows.all()]


# ----------------------------------------------------------------- papers


@action("papers.list", frames.PapersForQuery, "Ranked papers retrieved for a query")
async def papers_list(ctx: ActionContext, params: frames.PapersForQuery) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
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
        return [_dump(QueryPaperRead.from_query_paper(qp)) for qp in rows.all()]


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


@action("clusters.list", frames.QueryRef, "Clusters for a query, best evidence first")
async def clusters_list(ctx: ActionContext, params: frames.QueryRef) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        clusters = await cluster_edit.list_for_query(params.query_id, db)
        return [_dump(ClaimClusterRead.model_validate(c)) for c in clusters]


@action("clusters.get", frames.ClusterRef, "A cluster with its member claims and stances")
async def clusters_get(ctx: ActionContext, params: frames.ClusterRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return _dump(await cluster_edit.get_detail(params.cluster_id, db))


@action(
    "clusters.update",
    frames.ClusterPatch,
    "Override theme, summary, tier or drivers",
    cost="edit",
)
async def clusters_update(ctx: ActionContext, params: frames.ClusterPatch) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return _dump(await cluster_edit.update_cluster(params.cluster_id, params.patch, db))


@action(
    "clusters.set_stance",
    frames.ClusterStance,
    "Correct a claim's stance in a cluster",
    cost="edit",
)
async def clusters_set_stance(ctx: ActionContext, params: frames.ClusterStance) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return _dump(
            await cluster_edit.set_stance(params.cluster_id, params.claim_id, params.stance, db)
        )


@action("clusters.add_claim", frames.ClusterStance, "Move a claim into a cluster", cost="edit")
async def clusters_add_claim(ctx: ActionContext, params: frames.ClusterStance) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return _dump(
            await cluster_edit.add_claim(params.cluster_id, params.claim_id, params.stance, db)
        )


@action("clusters.remove_claim", frames.ClusterClaimRef, "Drop a claim from a cluster", cost="edit")
async def clusters_remove_claim(
    ctx: ActionContext, params: frames.ClusterClaimRef
) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await cluster_edit.remove_claim(params.cluster_id, params.claim_id, db)
        return {"removed": True, "claim_id": str(params.claim_id)}


# ----------------------------------------------------------------- report


@action("report.get", frames.QueryRef, "The synthesized three-axis report")
async def report_get(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        await _require_query(params.query_id, db)
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
        query = await _require_query(params.query_id, db)
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
        report = await report_edit.refresh_sources(params.query_id, db)
        return _dump(ReportRead.model_validate(report))


@action("report.update", frames.ReportPatch, "Edit report front matter or sections", cost="edit")
async def report_update(ctx: ActionContext, params: frames.ReportPatch) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
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
        report = await report_edit.update_section(
            params.query_id, params.cluster_id, params.patch, db
        )
        return _dump(ReportRead.model_validate(report))


@action("report.render", frames.RenderReport, "Rendered report HTML (screen or print variant)")
async def report_render_action(ctx: ActionContext, params: frames.RenderReport) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        query = await _require_query(params.query_id, db)
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
        query = await _require_query(params.query_id, db)
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
        answer = await report_chat.answer(params.query_id, params.question, params.history, db)
        return _dump(answer)


@action("report.pdf", frames.QueryRef, "Report as a PDF, base64-encoded for download")
async def report_pdf(ctx: ActionContext, params: frames.QueryRef) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        query = await _require_query(params.query_id, db)
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
