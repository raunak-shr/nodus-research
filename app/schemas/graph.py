"""The whole of one run, shaped for drawing rather than for reading.

Four views sit on top of this payload — clusters and their member claims, the
papers those claims came from, who wrote them, and the lineage between them —
and all four are the same run seen from different sides. So it is one response,
not four, and not one request per cluster: the paper list already learned that
a per-item fan-out sized by the corpus outgrows the socket's in-flight ceiling
and comes back looking like data loss.

Deliberately flat and small. Every string here is either an identifier or
something a label prints; nothing carries full text, and claims are the only
list that grows with the corpus. The layout is the client's business — a
position computed on the server would be wrong the moment the window resizes.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.models.cluster import QualityTier


class GraphPaperNode(BaseModel):
    id: UUID
    title: str
    #: Plain names, already unwrapped from the `{"name": ...}` records the
    #: paper row stores, because the authors view is built out of them.
    authors: list[str]
    year: int | None
    venue: str | None
    study_type: str | None
    citation_count: int
    rank: int
    claim_count: int
    #: True when this paper's text came from a file the reader uploaded rather
    #: than from retrieval — an upload has no citation count worth drawing.
    uploaded: bool
    #: Why this paper contributed nothing, when it contributed nothing. `None`
    #: for a paper that yielded claims, and for one still being processed.
    dropped_reason: str | None = None


class GraphClaimNode(BaseModel):
    id: UUID
    paper_id: UUID
    #: Trimmed server-side: the graph prints a citation, and the panel prints
    #: two lines. Neither wants the whole assertion.
    text: str
    citation: str
    stance: str
    confidence: float


class GraphClusterNode(BaseModel):
    id: UUID
    theme: str
    quality_tier: QualityTier
    support_count: int
    contradiction_count: int
    neutral_count: int
    paper_count: int
    claims: list[GraphClaimNode]


class GraphLineageEdge(BaseModel):
    """One step along a cluster's evidence lineage, oldest paper first.

    Not a citation: Nodus does not have the citation graph, and saying it did
    would be the one kind of lie an evidence tool cannot tell. This is the
    lineage `app/services/lineage.py` already builds — chronology plus the
    stance the cross-paper agent assigned — and `basis` says exactly that.
    """

    cluster_id: UUID
    from_paper_id: UUID
    to_paper_id: UUID
    relationship: str


class GraphRead(BaseModel):
    query_id: UUID
    question: str
    status: str
    #: Whether this run's corpus was retrieved or handed over. The four views
    #: read the same either way; only the caption changes.
    uploaded_corpus: bool
    papers: list[GraphPaperNode]
    clusters: list[GraphClusterNode]
    lineage: list[GraphLineageEdge]
    #: How the lineage edges were derived, carried through from the cluster's
    #: stored tree so the screen can say so under the view.
    lineage_basis: str
    #: Claims that reached no cluster, because `max_clusters_per_query`
    #: truncated to the largest ones. Counted rather than listed: the graph
    #: would be drawing nodes with no edges, but a reader still has to be told
    #: the field is not the whole run.
    claims_unclustered: int
