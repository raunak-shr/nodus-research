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
