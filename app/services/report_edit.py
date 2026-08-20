"""Phase 9 report edits, shared by the HTTP and WebSocket surfaces.

Any edit marks the report `user_edited`, which is what stops a later
regeneration from silently overwriting a human's wording.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.query import Query
from app.models.report import Report
from app.schemas.report import ReportUpdate, SectionNarrativeUpdate
from app.services import synthesizer
from app.services.errors import BadRequest, Conflict, NotFound


async def require_report(query_id: UUID, db: AsyncSession) -> Report:
    report = await synthesizer.load_report(query_id, db)
    if not report:
        raise NotFound("Report not generated yet", query_id=str(query_id))
    return report


async def regenerate(query: Query, db: AsyncSession) -> Report:
    """Rebuild the report from the current clusters, after edits."""
    report = await synthesizer.generate_report(query.id, query.raw_query, db)
    if not report:
        raise Conflict("No clusters available to synthesize", query_id=str(query.id))
    return report


async def refresh_sources(query_id: UUID, db: AsyncSession) -> Report:
    """Re-read every section's claim rows from the database, keeping the prose.

    `report.sections` is a JSONB snapshot and the PDF renders from it, so
    provenance recorded after a report was written does not appear — the claims
    in the document still carry whatever fields existed at synthesis time.

    Regenerating would fix that, but it costs an LLM call per cluster and rewrites
    narratives a human may have edited. Provenance is data, not prose: the claim
    rows can be replaced from current state on their own. No model is called, and
    every heading, narrative and caveat is left exactly as it was — so this does
    *not* set `user_edited`, because nothing a person wrote has changed.
    """
    report = await require_report(query_id, db)
    sections = list(report.sections or [])
    if not sections:
        raise Conflict("Report has no sections to refresh", query_id=str(query_id))

    clusters = await synthesizer.load_clusters(query_id, db)
    rows_by_cluster = {
        str(cluster.id): await synthesizer.section_claim_rows(cluster, db) for cluster in clusters
    }

    refreshed = 0
    for section in sections:
        rows = rows_by_cluster.get(str(section.get("cluster_id")))
        # Missing means the cluster was deleted; empty means it lost its members,
        # which is what a forced re-extraction does — deleting a claim cascades
        # through cluster_claims. Either way the section keeps its last known
        # claims: stale evidence beats none, and blanking a report is not a
        # refresh. `refreshed` stays 0, so the caller is told nothing changed.
        if not rows:
            continue
        section["claims"] = rows
        refreshed += 1

    if not refreshed:
        raise Conflict("No section matched a current cluster", query_id=str(query_id))

    # Reassigned rather than mutated in place: SQLAlchemy does not track changes
    # inside a JSONB value.
    report.sections = sections
    await db.commit()
    await db.refresh(report)
    return report


async def update(query_id: UUID, patch: ReportUpdate, db: AsyncSession) -> Report:
    """Edit report front matter, or replace sections wholesale."""
    report = await require_report(query_id, db)
    updates = patch.model_dump(exclude_unset=True)
    if not updates:
        raise BadRequest("No fields to update")

    for field, value in updates.items():
        setattr(report, field, value)
    report.user_edited = True
    await db.commit()
    await db.refresh(report)
    return report


async def update_section(
    query_id: UUID,
    cluster_id: UUID,
    patch: SectionNarrativeUpdate,
    db: AsyncSession,
) -> Report:
    """Edit one section's prose in place, leaving its evidence untouched."""
    report = await require_report(query_id, db)
    updates = patch.model_dump(exclude_unset=True)
    if not updates:
        raise BadRequest("No fields to update")

    sections = list(report.sections or [])
    for section in sections:
        if section.get("cluster_id") == str(cluster_id):
            section.update(updates)
            break
    else:
        raise NotFound("Section not found in report", cluster_id=str(cluster_id))

    report.sections = sections
    report.user_edited = True
    await db.commit()
    await db.refresh(report)
    return report
