"""The papers table's claim count comes from the claims, not from the report.

Clustering truncates to the largest `max_clusters_per_query` clusters, so claims
in smaller ones reach no report section. Deriving the per-paper count from the
report therefore reported those papers as having contributed nothing — measured
on one run as 72 claims extracted, 48 clustered, and five papers shown as empty
that had real evidence in them. The two states have different remedies and must
not render the same, so the extracted count travels with the row.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.models.paper import ProcessingStatus, StudyType
from app.services import paper_listing


def _paper(paper_id: UUID, normalized=None):
    return SimpleNamespace(
        id=paper_id,
        semantic_scholar_id=f"ss-{paper_id}",
        doi=None,
        arxiv_id=None,
        title="Adaptive retrieval under question complexity",
        abstract="An abstract.",
        authors=[{"name": "A. Author"}],
        publication_year=2024,
        venue="Proceedings",
        citation_count=616,
        influential_citation_count=40,
        fields_of_study=[],
        open_access_pdf_url=None,
        tldr=None,
        created_at=datetime.now(UTC),
        normalized_paper=normalized,
    )


def _normalized():
    return SimpleNamespace(
        study_type=StudyType.observational,
        methodology={"design": "computational evaluation"},
        has_full_text=True,
        full_text_source="doi",
        processing_status=ProcessingStatus.completed,
    )


def _query_paper(paper_id: UUID, rank: int):
    return SimpleNamespace(
        paper_id=paper_id, paper=_paper(paper_id, _normalized()), rank=rank, ranking_score=0.5
    )


class _StubSession:
    """An AsyncSession stand-in that answers exactly one grouped count query."""

    def __init__(self, counts: dict[UUID, int]):
        self._counts = counts
        self.executions = 0

    async def execute(self, _statement):
        self.executions += 1
        rows = list(self._counts.items())
        return SimpleNamespace(all=lambda: rows)


@pytest.mark.asyncio
async def test_a_paper_whose_claims_missed_every_cluster_still_counts_them():
    """The bug in one assertion.

    This paper's claims exist; none of them landed in a cluster that survived
    the cap. Counted from the report it read as `0 claims`, which the UI could
    only describe as a paper nothing was indexed for.
    """
    paper_id = uuid4()
    db = _StubSession({paper_id: 3})

    rows = await paper_listing.read_query_papers([_query_paper(paper_id, 1)], db)

    assert rows[0].claim_count == 3


@pytest.mark.asyncio
async def test_a_paper_with_no_claims_reports_zero():
    paper_id = uuid4()
    db = _StubSession({})

    rows = await paper_listing.read_query_papers([_query_paper(paper_id, 1)], db)

    assert rows[0].claim_count == 0
    # Absent from the count query and genuinely empty are the same state here,
    # and both are distinct from a normalisation that failed.
    assert rows[0].normalized.processing_status == ProcessingStatus.completed


@pytest.mark.asyncio
async def test_a_whole_page_of_papers_costs_one_count_query():
    """Same guarantee `normalized` earned: no per-paper fan-out.

    A count read per row would be N queries inside a serialisation loop, and if
    it were ever done as a per-paper *request* it would be the in-flight-ceiling
    regression that carrying normalisation inline exists to prevent.
    """
    query_papers = [_query_paper(uuid4(), rank) for rank in range(1, 21)]
    db = _StubSession({qp.paper_id: 2 for qp in query_papers})

    rows = await paper_listing.read_query_papers(query_papers, db)

    assert db.executions == 1
    assert [row.claim_count for row in rows] == [2] * 20


@pytest.mark.asyncio
async def test_an_empty_list_asks_the_database_nothing():
    db = _StubSession({})

    assert await paper_listing.read_query_papers([], db) == []
    assert db.executions == 0
