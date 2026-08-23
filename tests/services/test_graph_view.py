"""The graph payload — one run assembled for drawing.

Hermetic: the session is a stub that answers the three queries `build_graph`
issues, in order. The point of these tests is what the payload *claims*, not
that SQLAlchemy works.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.models.cluster import ClaimCluster, QualityTier
from app.models.paper import NormalizedPaper, Paper, ProcessingStatus, QueryPaper, StudyType
from app.models.query import Query, QueryStatus
from app.services import cluster_edit, graph, uploads

P1 = uuid4()
P2 = uuid4()
P3 = uuid4()


def _paper(paper_id, title, year, *, authors=None, uploaded=False, normalized=True, failed=False):
    paper = Paper(
        id=paper_id,
        semantic_scholar_id=uploads.fingerprint(title.encode()) if uploaded else f"ss-{title}",
        title=title,
        authors=authors if authors is not None else [{"name": "A Researcher"}],
        publication_year=year,
        venue="A Journal",
        citation_count=10,
    )
    paper.normalized_paper = (
        NormalizedPaper(
            paper_id=paper_id,
            full_text=None if failed else "body",
            study_type=StudyType.rct,
            processing_status=ProcessingStatus.failed if failed else ProcessingStatus.completed,
        )
        if normalized
        else None
    )
    return paper


def _link(paper, rank):
    link = QueryPaper(query_id=uuid4(), paper_id=paper.id, rank=rank)
    link.paper = paper
    return link


class _StubDb:
    """Answers `build_graph`'s three reads, in the order it makes them.

    Three, not three-plus-one-per-cluster: the member claims come back in a
    single read keyed by cluster, and a stub that still served them one cluster
    at a time would let that regress unnoticed.
    """

    def __init__(self, links, counts, cluster_claims) -> None:
        self.links = links
        self.counts = counts
        # Flattened the way the real query returns them, then grouped by the
        # code under test.
        self.members = [row for group in cluster_claims for row in group]
        self.calls = 0

    async def execute(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.links))
        if self.calls == 2:
            return SimpleNamespace(all=lambda: self.counts)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.members))


def _cluster(theme, lineage=None, **kwargs):
    return ClaimCluster(
        id=uuid4(),
        query_id=uuid4(),
        central_theme=theme,
        lineage_tree=lineage,
        support_count=kwargs.get("support", 3),
        neutral_count=0,
        contradiction_count=kwargs.get("contradicts", 1),
        quality_tier=QualityTier.high,
    )


def _member(claim_id, paper_id, text, stance="supports"):
    link = SimpleNamespace(stance=stance)
    link.claim = SimpleNamespace(
        id=claim_id, paper_id=paper_id, claim_text=text, confidence_score=0.8
    )
    return link


def _query(status=QueryStatus.completed):
    return Query(id=uuid4(), raw_query="Does aerobic exercise reduce depression?", status=status)


async def _build(links, counts, clusters, cluster_claims, query=None):
    # Members arrive from one query for every cluster at once, so each has to
    # say which cluster it belongs to — the grouping is what is under test.
    for cluster, group in zip(clusters, cluster_claims, strict=False):
        for row in group:
            row.cluster_id = cluster.id
    with patch.object(cluster_edit, "list_for_query", AsyncMock(return_value=clusters)):
        return await graph.build_graph(query or _query(), _StubDb(links, counts, cluster_claims))


# -- lineage ----------------------------------------------------------------


async def test_lineage_edges_are_consecutive_steps_not_a_star():
    """The chain is chronological, so `i-1 → i` is the step the tree asserts.

    A star from the origin would draw every later paper as a direct descendant
    of the first, which the tree does not claim and chronology does not support.
    """
    chain = [
        {"paper_id": str(P1), "relationship": "origin"},
        {"paper_id": str(P2), "relationship": "supports"},
        {"paper_id": str(P3), "relationship": "contradicts"},
    ]
    cluster = _cluster("Effect size", {"chain": chain, "basis": "chronological+stance"})
    links = [
        _link(_paper(P1, "A", 2007), 1),
        _link(_paper(P2, "B", 2013), 2),
        _link(_paper(P3, "C", 2024), 3),
    ]

    payload = await _build(links, [(P1, 2), (P2, 1), (P3, 1)], [cluster], [[]])

    assert [(e.from_paper_id, e.to_paper_id, e.relationship) for e in payload.lineage] == [
        (P1, P2, "supports"),
        (P2, P3, "contradicts"),
    ]
    assert payload.lineage_basis == "chronological+stance"


async def test_a_chain_node_for_a_paper_no_longer_in_the_run_is_skipped():
    """A cluster outlives an edit that took a paper out of the run.

    Drawing the edge anyway would put a line to nowhere on the field.
    """
    chain = [
        {"paper_id": str(P1), "relationship": "origin"},
        {"paper_id": str(uuid4()), "relationship": "supports"},
        {"paper_id": str(P2), "relationship": "extends"},
    ]
    cluster = _cluster("Effect size", {"chain": chain})
    links = [_link(_paper(P1, "A", 2007), 1), _link(_paper(P2, "B", 2013), 2)]

    payload = await _build(links, [(P1, 1), (P2, 1)], [cluster], [[]])

    assert [(e.from_paper_id, e.to_paper_id) for e in payload.lineage] == [(P1, P2)]


async def test_a_cluster_with_no_lineage_tree_contributes_no_edges():
    cluster = _cluster("Effect size", None)
    links = [_link(_paper(P1, "A", 2007), 1)]

    payload = await _build(links, [(P1, 1)], [cluster], [[]])

    assert payload.lineage == []
    # Still named rather than left empty: the screen prints it under the view.
    assert payload.lineage_basis == "chronological+stance"


# -- what the papers say about themselves -----------------------------------


async def test_a_paper_that_yielded_nothing_says_why_only_once_the_run_stopped():
    """Mid-run, a paper with no claims is a paper whose turn has not come."""
    links = [_link(_paper(P1, "A", 2007, normalized=False), 1)]

    running = await _build(links, [], [], [], query=_query(QueryStatus.processing))
    assert running.papers[0].dropped_reason is None

    finished = await _build(links, [], [], [], query=_query(QueryStatus.completed))
    assert finished.papers[0].dropped_reason == "Not processed"


async def test_a_normalised_paper_that_lost_its_claims_is_a_different_state():
    links = [_link(_paper(P1, "A", 2007, failed=True), 1)]
    payload = await _build(links, [], [], [], query=_query(QueryStatus.completed))
    assert "failed" in payload.papers[0].dropped_reason


async def test_authors_arrive_as_plain_names_for_the_authors_view():
    links = [
        _link(
            _paper(P1, "A", 2007, authors=[{"name": "J Blumenthal"}, {}, {"name": " "}]),
            1,
        )
    ]
    payload = await _build(links, [(P1, 1)], [], [])
    assert payload.papers[0].authors == ["J Blumenthal"]


async def test_an_uploaded_corpus_is_reported_as_one():
    links = [
        _link(_paper(P1, "A", 2007, uploaded=True), 1),
        _link(_paper(P2, "B", 2013, uploaded=True), 2),
    ]
    payload = await _build(links, [(P1, 1), (P2, 1)], [], [])

    assert payload.uploaded_corpus is True
    assert all(paper.uploaded for paper in payload.papers)


async def test_a_mixed_corpus_is_not_an_uploaded_one():
    links = [_link(_paper(P1, "A", 2007, uploaded=True), 1), _link(_paper(P2, "B", 2013), 2)]
    payload = await _build(links, [(P1, 1), (P2, 1)], [], [])
    assert payload.uploaded_corpus is False


# -- the gap the field cannot show ------------------------------------------


async def test_claims_that_reached_no_cluster_are_counted_not_hidden():
    """`max_clusters_per_query` truncates, so a run's claims outnumber its
    clustered ones. The field draws only what clustered; the count is what
    stops that reading as the whole run."""
    cluster = _cluster("Effect size")
    links = [_link(_paper(P1, "A", 2007), 1), _link(_paper(P2, "B", 2013), 2)]
    claim_a, claim_b = uuid4(), uuid4()

    payload = await _build(
        links,
        [(P1, 9), (P2, 4)],
        [cluster],
        [[_member(claim_a, P1, "One"), _member(claim_b, P2, "Two")]],
    )

    assert payload.claims_unclustered == 11
    assert payload.clusters[0].paper_count == 2
    assert len(payload.clusters[0].claims) == 2


async def test_a_claim_carries_the_citation_of_the_paper_it_came_from():
    cluster = _cluster("Effect size")
    links = [_link(_paper(P1, "A", 2007, authors=[{"name": "James Blumenthal"}]), 1)]

    payload = await _build(links, [(P1, 1)], [cluster], [[_member(uuid4(), P1, "One")]])

    assert payload.clusters[0].claims[0].citation == "Blumenthal, 2007"


async def test_a_long_claim_is_trimmed_so_the_frame_stays_small():
    cluster = _cluster("Effect size")
    links = [_link(_paper(P1, "A", 2007), 1)]

    payload = await _build(links, [(P1, 1)], [cluster], [[_member(uuid4(), P1, "x" * 2000)]])

    assert len(payload.clusters[0].claims[0].text) == graph._CLAIM_CHARS


async def test_the_whole_field_is_three_reads_however_many_clusters_there_are():
    """The mistake this screen was built to avoid.

    A read per cluster is a round trip per cluster against a pooled hosted
    database, and `max_clusters_per_query` allows twenty-five of them.
    """
    clusters = [_cluster(f"Theme {i}") for i in range(12)]
    links = [_link(_paper(P1, "A", 2007), 1)]
    groups = [[_member(uuid4(), P1, "One")] for _ in clusters]
    for cluster, group in zip(clusters, groups, strict=True):
        group[0].cluster_id = cluster.id
    db = _StubDb(links, [(P1, 12)], groups)

    with patch.object(cluster_edit, "list_for_query", AsyncMock(return_value=clusters)):
        payload = await graph.build_graph(_query(), db)

    assert db.calls == 3
    assert len(payload.clusters) == 12
    assert all(len(cluster.claims) == 1 for cluster in payload.clusters)
