"""One run, assembled as a graph.

Four views, one query. Everything here already exists somewhere else in the
database — this module joins it once instead of leaving a client to fan out per
cluster and per paper, which is the mistake `paper_listing` was written to undo.

The lineage view is the one that needs saying out loud. It is **not** a citation
graph: Semantic Scholar's bulk search returns no citation edges, so Nodus has
never had them, and drawing invented ones under the word "lineage" would put
untraceable structure beside traceable claims. What it draws instead is the
evidence lineage Axis 1 already computes and stores on every cluster — which
paper stated the claim first, and how each later paper relates to it — laid out
by publication year. `lineage_basis` carries the tree's own account of how it
was derived so the screen can print it rather than imply something stronger.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.claim import Claim
from app.models.cluster import ClaimCluster, ClusterClaim
from app.models.paper import NormalizedPaper, Paper, ProcessingStatus, QueryPaper
from app.models.query import Query
from app.schemas.graph import (
    GraphClaimNode,
    GraphClusterNode,
    GraphLineageEdge,
    GraphPaperNode,
    GraphRead,
)
from app.services import cluster_edit, uploads

#: Long enough for the pinned-node panel to read as a claim, short enough that
#: a twenty-paper run's worth of them is still a small frame.
_CLAIM_CHARS = 320


def _author_names(paper: Paper) -> list[str]:
    names: list[str] = []
    for entry in paper.authors or []:
        name = entry.get("name") if isinstance(entry, dict) else None
        if name and str(name).strip():
            names.append(str(name).strip())
    return names


def _dropped_reason(
    normalized: NormalizedPaper | None,
    claim_count: int,
    run_finished: bool,
) -> str | None:
    """Why a paper contributed nothing — or None, when it did or still might.

    "No record" and "record that failed" are different states and must not be
    merged, and neither of them means anything at all while the run is still
    going. Mid-run a paper with no claims is a paper whose turn has not come.
    """
    if claim_count:
        return None
    if normalized is None:
        return "Not processed" if run_finished else None
    if normalized.processing_status == ProcessingStatus.failed:
        return "Normalized, then failed before claims were stored"
    if not run_finished:
        return None
    if not normalized.has_full_text:
        return "No full text was reachable; nothing above the extraction threshold"
    return "No claim above the extraction threshold"


def _lineage_edges(cluster: ClaimCluster, known_papers: set[UUID]) -> list[GraphLineageEdge]:
    """Consecutive links along one cluster's stored lineage chain.

    Consecutive rather than a star from the origin: the chain is chronological,
    so link `i-1 → i` is the step the tree actually asserts, and a star would
    draw every paper as a direct descendant of the first one — which the tree
    does not claim and the chronology does not support.
    """
    tree: dict[str, Any] = cluster.lineage_tree or {}
    chain = tree.get("chain") or []
    edges: list[GraphLineageEdge] = []
    previous: UUID | None = None
    for node in chain:
        raw = node.get("paper_id") if isinstance(node, dict) else None
        if not raw:
            continue
        try:
            paper_id = UUID(str(raw))
        except ValueError:
            continue
        # A cluster can outlive an edit that removed a paper from the run.
        if paper_id not in known_papers:
            continue
        if previous is not None and previous != paper_id:
            edges.append(
                GraphLineageEdge(
                    cluster_id=cluster.id,
                    from_paper_id=previous,
                    to_paper_id=paper_id,
                    relationship=str(node.get("relationship") or "extends"),
                )
            )
        previous = paper_id
    return edges


async def build_graph(query: Query, db: AsyncSession) -> GraphRead:
    """Everything the Graph screen draws, in one read.

    The caller has already established that this query is the reader's to see —
    ownership is checked on the query, not here.
    """
    query_papers = (
        (
            await db.execute(
                select(QueryPaper)
                .where(QueryPaper.query_id == query.id)
                .options(
                    selectinload(QueryPaper.paper).selectinload(Paper.normalized_paper),
                )
                .order_by(QueryPaper.rank)
            )
        )
        .scalars()
        .all()
    )
    papers = [link.paper for link in query_papers if link.paper is not None]
    paper_ids = {paper.id for paper in papers}

    claim_counts: dict[UUID, int] = {}
    if paper_ids:
        rows = await db.execute(
            select(Claim.paper_id, func.count(Claim.id))
            .where(Claim.paper_id.in_(paper_ids))
            .group_by(Claim.paper_id)
        )
        claim_counts = {pid: int(count) for pid, count in rows.all()}

    run_finished = str(query.status) in {"completed", "failed"}

    paper_nodes = [
        GraphPaperNode(
            id=link.paper.id,
            title=link.paper.title,
            authors=_author_names(link.paper),
            year=link.paper.publication_year,
            venue=link.paper.venue,
            study_type=(
                str(link.paper.normalized_paper.study_type) if link.paper.normalized_paper else None
            ),
            citation_count=link.paper.citation_count,
            rank=link.rank,
            claim_count=claim_counts.get(link.paper.id, 0),
            uploaded=uploads.is_upload(link.paper),
            dropped_reason=_dropped_reason(
                link.paper.normalized_paper,
                claim_counts.get(link.paper.id, 0),
                run_finished,
            ),
        )
        for link in query_papers
        if link.paper is not None
    ]

    clusters = await cluster_edit.list_for_query(query.id, db)
    cluster_nodes: list[GraphClusterNode] = []
    lineage: list[GraphLineageEdge] = []
    lineage_basis = ""
    clustered_claims: set[UUID] = set()

    # Every cluster's members in one read, not one read per cluster. The same
    # rule the paper list learned: a per-item fan-out sized by the run is a
    # round trip per item, and against a pooled hosted database twenty-five of
    # those is the whole latency of this screen.
    members: dict[UUID, list[ClusterClaim]] = {}
    if clusters:
        rows = (
            (
                await db.execute(
                    select(ClusterClaim)
                    .where(ClusterClaim.cluster_id.in_([cluster.id for cluster in clusters]))
                    .options(selectinload(ClusterClaim.claim))
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            members.setdefault(row.cluster_id, []).append(row)

    by_paper = {paper.id: paper for paper in papers}
    for cluster in clusters:
        links = members.get(cluster.id, [])
        claim_nodes: list[GraphClaimNode] = []
        cluster_papers: set[UUID] = set()
        for link in links:
            claim = link.claim
            if claim is None:
                continue
            clustered_claims.add(claim.id)
            paper = by_paper.get(claim.paper_id)
            cluster_papers.add(claim.paper_id)
            claim_nodes.append(
                GraphClaimNode(
                    id=claim.id,
                    paper_id=claim.paper_id,
                    text=claim.claim_text[:_CLAIM_CHARS],
                    citation=cluster_edit.citation(paper) if paper else "Unknown",
                    stance=link.stance,
                    confidence=claim.confidence_score,
                )
            )
        cluster_nodes.append(
            GraphClusterNode(
                id=cluster.id,
                theme=cluster.central_theme,
                quality_tier=cluster.quality_tier,
                support_count=cluster.support_count,
                contradiction_count=cluster.contradiction_count,
                neutral_count=cluster.neutral_count,
                paper_count=len(cluster_papers),
                claims=claim_nodes,
            )
        )
        lineage.extend(_lineage_edges(cluster, paper_ids))
        if not lineage_basis:
            lineage_basis = str((cluster.lineage_tree or {}).get("basis") or "")

    total_claims = sum(claim_counts.values())

    return GraphRead(
        query_id=query.id,
        question=query.raw_query,
        status=str(query.status),
        uploaded_corpus=bool(papers) and all(uploads.is_upload(paper) for paper in papers),
        papers=paper_nodes,
        clusters=cluster_nodes,
        lineage=lineage,
        lineage_basis=lineage_basis or "chronological+stance",
        claims_unclustered=max(0, total_claims - len(clustered_claims)),
    )
