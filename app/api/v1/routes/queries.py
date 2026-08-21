"""Query lifecycle: submit, track, stream progress, report, export, follow up."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from fastapi import Query as QueryParam
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.v1.deps import (
    AdminCaller,
    DBSession,
    EditRateLimit,
    InterpretRateLimit,
    Owner,
    PageParams,
    RunRateLimit,
)
from app.core.events import hub
from app.models.paper import Paper, QueryPaper
from app.models.query import Query, QueryStatus
from app.schemas.paper import QueryPaperRead
from app.schemas.query import (
    QueryCreate,
    QueryInterpret,
    QueryInterpretation,
    QueryRead,
    QueryWithPapersRead,
)
from app.schemas.report import FollowUpCreate, ReportRead, ReportUpdate, SectionNarrativeUpdate
from app.services import export, ownership, query_assessor, report_edit, runner, synthesizer
from app.services.errors import Forbidden
from app.services.pipeline import run_pipeline_safe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/queries", tags=["queries"])


def _require_admin_for_wait(wait: bool, admin: bool) -> None:
    """`wait=true` runs the pipeline inside the request.

    That holds the request-scoped database session for the whole run, so a
    handful of concurrent callers can exhaust the connection pool and stall
    every other endpoint. It stays admin-only; everyone else subscribes to the
    progress stream, which is what the flag is a poor substitute for anyway.
    """
    if wait and not admin:
        raise Forbidden(
            "wait=true is admin-only — subscribe to the progress stream instead",
            hint="GET /api/v1/queries/{query_id}/stream",
        )


async def cancel_background_tasks() -> None:
    """Cancel in-flight pipelines on shutdown."""
    await runner.cancel_all()


@router.post("/", response_model=QueryRead, status_code=201, dependencies=[RunRateLimit])
async def create_query(
    body: QueryCreate,
    db: DBSession,
    admin: AdminCaller,
    owner: Owner,
    wait: bool = QueryParam(
        False,
        description="Admin only. Run the pipeline inline and return only when it "
        "finishes. Off by default: a full run takes minutes.",
    ),
) -> QueryRead:
    """Submit a research query and start the pipeline.

    Refused with 429 when MAX_ACTIVE_QUERIES runs are already in flight — the
    slot is reserved before the row is written, so a refusal leaves nothing
    behind.
    """
    _require_admin_for_wait(wait, admin)

    async with runner.admission() as reserved:
        query = Query(raw_query=body.query, status=QueryStatus.pending, owner_key=owner)
        db.add(query)
        await db.commit()
        await db.refresh(query)

        if wait:
            await run_pipeline_safe(query.id, body.query)
            await db.refresh(query)
        else:
            reserved.launch(query.id, body.query)

    return QueryRead.model_validate(query)


@router.post(
    "/interpret",
    response_model=QueryInterpretation,
    dependencies=[InterpretRateLimit],
)
async def interpret_query(body: QueryInterpret) -> QueryInterpretation:
    """Read a question back and say whether running it is worth the five minutes.

    Nothing is stored and no run is started: this is the check a caller makes
    *before* POST /queries. A verdict other than `ready` is advice, not a
    refusal — the question can still be submitted exactly as typed.
    """
    return await query_assessor.interpret(body.query)


@router.get("/", response_model=list[QueryRead])
async def list_queries(
    db: DBSession, page: PageParams, owner: Owner, admin: AdminCaller
) -> list[QueryRead]:
    """List this caller's queries, newest first.

    Scoped on `owner_key`: a listing is a history, and one reader's history is
    not another's. Rows written before ownership existed carry no owner and are
    visible with the admin key only.
    """
    result = await db.execute(
        ownership.scope(select(Query), owner, is_admin=admin)
        .order_by(Query.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return [QueryRead.model_validate(q) for q in result.scalars().all()]


@router.get("/{query_id}", response_model=QueryWithPapersRead)
async def get_query(
    query_id: UUID, db: DBSession, owner: Owner, admin: AdminCaller
) -> QueryWithPapersRead:
    """Return query status and ranked papers."""
    query = await _get_query_or_404(query_id, db, owner, admin)

    qp_result = await db.execute(
        select(QueryPaper)
        .where(QueryPaper.query_id == query_id)
        .options(selectinload(QueryPaper.paper).selectinload(Paper.normalized_paper))
        .order_by(QueryPaper.rank)
    )
    query_papers = qp_result.scalars().all()

    return QueryWithPapersRead(
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


@router.get("/{query_id}/progress")
async def get_progress(query_id: UUID, db: DBSession, owner: Owner, admin: AdminCaller) -> dict:
    """Replay the progress events recorded for a query (WebSocket alternative)."""
    query = await _get_query_or_404(query_id, db, owner, admin)
    return {
        "query_id": str(query_id),
        "status": str(query.status),
        "error_message": query.error_message,
        "events": hub.history(query_id),
    }


@router.get("/{query_id}/report", response_model=ReportRead)
async def get_report(query_id: UUID, db: DBSession, owner: Owner, admin: AdminCaller) -> ReportRead:
    """Return the synthesized three-axis report."""
    await _get_query_or_404(query_id, db, owner, admin)
    report = await synthesizer.load_report(query_id, db)
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet")
    return ReportRead.model_validate(report)


@router.post(
    "/{query_id}/report",
    response_model=ReportRead,
    status_code=201,
    dependencies=[RunRateLimit],
)
async def regenerate_report(
    query_id: UUID, db: DBSession, owner: Owner, admin: AdminCaller
) -> ReportRead:
    """Regenerate the report from current clusters (after user edits)."""
    query = await _get_query_or_404(query_id, db, owner, admin)
    report = await synthesizer.generate_report(query_id, query.raw_query, db)
    if not report:
        raise HTTPException(status_code=409, detail="No clusters available to synthesize")
    return ReportRead.model_validate(report)


@router.post(
    "/{query_id}/report/sources",
    response_model=ReportRead,
    dependencies=[EditRateLimit],
)
async def refresh_report_sources(
    query_id: UUID, db: DBSession, owner: Owner, admin: AdminCaller
) -> ReportRead:
    """Refresh the claim rows behind each section without re-synthesising.

    An edit, not a run: no model is called, so it is throttled as a database
    write rather than through the pipeline gate. Narratives and caveats are left
    untouched, which is the point — a regeneration would rewrite them.
    """
    await _get_query_or_404(query_id, db, owner, admin)
    return ReportRead.model_validate(await report_edit.refresh_sources(query_id, db))


@router.patch("/{query_id}/report", response_model=ReportRead, dependencies=[EditRateLimit])
async def update_report(
    query_id: UUID, body: ReportUpdate, db: DBSession, owner: Owner, admin: AdminCaller
) -> ReportRead:
    """Phase 9 — edit report front matter or replace sections wholesale."""
    await _get_query_or_404(query_id, db, owner, admin)
    report = await synthesizer.load_report(query_id, db)
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    for field, value in updates.items():
        setattr(report, field, value)
    report.user_edited = True
    await db.commit()
    await db.refresh(report)
    return ReportRead.model_validate(report)


@router.patch(
    "/{query_id}/report/sections/{cluster_id}",
    response_model=ReportRead,
    dependencies=[EditRateLimit],
)
async def update_report_section(
    query_id: UUID,
    cluster_id: UUID,
    body: SectionNarrativeUpdate,
    db: DBSession,
    owner: Owner,
    admin: AdminCaller,
) -> ReportRead:
    """Phase 9 — edit one section's prose in place."""
    await _get_query_or_404(query_id, db, owner, admin)
    report = await synthesizer.load_report(query_id, db)
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet")

    updates = body.model_dump(exclude_unset=True)
    sections = list(report.sections or [])
    for section in sections:
        if section.get("cluster_id") == str(cluster_id):
            section.update(updates)
            break
    else:
        raise HTTPException(status_code=404, detail="Section not found in report")

    report.sections = sections
    report.user_edited = True
    await db.commit()
    await db.refresh(report)
    return ReportRead.model_validate(report)


@router.get("/{query_id}/report/export")
async def export_report(
    query_id: UUID,
    db: DBSession,
    owner: Owner,
    admin: AdminCaller,
    format: str = QueryParam("markdown", pattern="^(markdown|md|json|html)$"),
) -> Response:
    """Export the report as markdown, JSON, or print-ready HTML (→ PDF)."""
    query = await _get_query_or_404(query_id, db, owner, admin)
    report = await synthesizer.load_report(query_id, db)
    if not report:
        raise HTTPException(status_code=404, detail="Report not generated yet")

    slug = str(query_id)[:8]
    if format == "json":
        return Response(
            content=export.to_json(report, query),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="nodus-{slug}.json"'},
        )
    if format == "html":
        return Response(content=export.to_html(report, query), media_type="text/html")
    return Response(
        content=export.to_markdown(report, query),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="nodus-{slug}.md"'},
    )


@router.post(
    "/{query_id}/followup",
    response_model=QueryRead,
    status_code=201,
    dependencies=[RunRateLimit],
)
async def create_followup(
    query_id: UUID,
    body: FollowUpCreate,
    db: DBSession,
    admin: AdminCaller,
    owner: Owner,
    wait: bool = QueryParam(
        False, description="Admin only. Run inline instead of in the background"
    ),
) -> QueryRead:
    """Phase 10 — ask a follow-up that narrows a previous query.

    The follow-up runs the full pipeline scoped by the parent question, and is
    linked to its parent so the refinement chain stays inspectable. It costs a
    full run, so it is admitted through the same gate as a new query.
    """
    _require_admin_for_wait(wait, admin)

    # Admitted before the parent lookup, so a submission refused for capacity
    # does not cost a database round trip — and so this matches the v2 action.
    async with runner.admission() as reserved:
        parent = await _get_query_or_404(query_id, db, owner, admin)
        combined = f"{parent.raw_query} — follow-up: {body.query}"
        child = Query(
            raw_query=body.query,
            status=QueryStatus.pending,
            parent_query_id=parent.id,
            # The follow-up is the parent's owner's, not the caller's: an admin
            # narrowing someone's question must not take the run away from them.
            owner_key=parent.owner_key or owner,
        )
        db.add(child)
        await db.commit()
        await db.refresh(child)

        if wait:
            await run_pipeline_safe(child.id, combined)
            await db.refresh(child)
        else:
            reserved.launch(child.id, combined)

    return QueryRead.model_validate(child)


@router.get("/{query_id}/followups", response_model=list[QueryRead])
async def list_followups(
    query_id: UUID, db: DBSession, owner: Owner, admin: AdminCaller
) -> list[QueryRead]:
    await _get_query_or_404(query_id, db, owner, admin)
    result = await db.execute(
        select(Query).where(Query.parent_query_id == query_id).order_by(Query.created_at)
    )
    return [QueryRead.model_validate(q) for q in result.scalars().all()]


@router.delete("/{query_id}", status_code=204, dependencies=[EditRateLimit])
async def delete_query(query_id: UUID, db: DBSession, owner: Owner, admin: AdminCaller) -> Response:
    """Delete a query and everything derived from it (papers stay global)."""
    query = await _get_query_or_404(query_id, db, owner, admin)
    await db.delete(query)
    await db.commit()
    hub.clear(query_id)
    return Response(status_code=204)


@router.get("/{query_id}/stats")
async def query_stats(query_id: UUID, db: DBSession, owner: Owner, admin: AdminCaller) -> dict:
    """Counts across the pipeline — the quickest health check for a run."""
    from app.models.claim import Claim
    from app.models.cluster import ClaimCluster

    query = await _get_query_or_404(query_id, db, owner, admin)

    claim_count = (
        await db.execute(
            select(func.count(Claim.id))
            .join(QueryPaper, QueryPaper.paper_id == Claim.paper_id)
            .where(QueryPaper.query_id == query_id)
        )
    ).scalar_one()
    cluster_count = (
        await db.execute(
            select(func.count(ClaimCluster.id)).where(ClaimCluster.query_id == query_id)
        )
    ).scalar_one()
    report = await synthesizer.load_report(query_id, db)

    return {
        "query_id": str(query_id),
        "status": str(query.status),
        "paper_count": query.paper_count,
        "claim_count": claim_count,
        "cluster_count": cluster_count,
        "report_sections": len(report.sections or []) if report else 0,
    }


async def _get_query_or_404(
    query_id: UUID, db: DBSession, owner: str, admin: bool = False
) -> Query:
    """The query, if it belongs to this caller.

    Every route here goes through this one function, which is why scoping the
    surface was a change to it rather than to twelve handlers. Someone else's
    query is a 404 and not a 403: a 403 confirms the id exists, which is the
    fact being withheld.
    """
    return await ownership.require_query(query_id, db, owner=owner, is_admin=admin)
