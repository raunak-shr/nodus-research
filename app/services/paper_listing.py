"""Turning `QueryPaper` rows into the shape a table of papers needs.

A paper's claim count is not a column on the paper — it is a count of `claims`
rows — and it is the number the papers table means by "claims". The table used
to derive it from the report instead, which undercounts every paper whose claims
fell outside `max_clusters_per_query`: on a measured run, 72 claims were
extracted, 48 were clustered, and five papers that had contributed real evidence
were shown as having contributed none.

Counted for the whole list in one grouped query rather than per row. A per-paper
read would be N queries inside a serialisation loop, and over the v2 socket a
per-paper *request* would be the fan-out that carrying `normalized` inline
exists to avoid — see `QueryPaperRead`.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.claim import Claim
from app.models.paper import QueryPaper
from app.schemas.paper import QueryPaperRead


async def claim_counts(paper_ids: Sequence[UUID], db: AsyncSession) -> dict[UUID, int]:
    """How many claims are stored for each of `paper_ids`.

    Papers with no claims are absent from the mapping rather than present as
    zero; callers read it with a default so the two are the same to them.
    """
    unique = set(paper_ids)
    if not unique:
        return {}
    rows = await db.execute(
        select(Claim.paper_id, func.count(Claim.id))
        .where(Claim.paper_id.in_(unique))
        .group_by(Claim.paper_id)
    )
    return {paper_id: count for paper_id, count in rows.all()}


async def read_query_papers(
    query_papers: Sequence[QueryPaper], db: AsyncSession
) -> list[QueryPaperRead]:
    """Serialise ranked papers with their normalisation and claim count inline.

    `query_papers` must have been loaded with `paper.normalized_paper` eager,
    which `QueryPaperRead.from_query_paper` requires.
    """
    counts = await claim_counts([qp.paper_id for qp in query_papers], db)
    return [
        QueryPaperRead.from_query_paper(qp, claim_count=counts.get(qp.paper_id, 0))
        for qp in query_papers
    ]
