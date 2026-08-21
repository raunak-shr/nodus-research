from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.paper import ProcessingStatus, StudyType


class PaperRead(BaseModel):
    id: UUID
    semantic_scholar_id: str
    doi: str | None
    arxiv_id: str | None = None
    title: str
    abstract: str | None
    authors: list[dict[str, Any]]
    publication_year: int | None
    venue: str | None
    citation_count: int
    influential_citation_count: int
    fields_of_study: list[Any]
    open_access_pdf_url: str | None
    tldr: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NormalizedPaperRead(BaseModel):
    id: UUID
    paper_id: UUID
    study_type: StudyType
    methodology: dict[str, Any] | None = None
    sections: dict[str, Any] | None = None
    has_full_text: bool = False
    full_text_source: str | None = None
    processing_status: ProcessingStatus
    llm_model_used: str | None
    processed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NormalizedPaperSummary(BaseModel):
    """What a list of papers needs from normalisation, and nothing more.

    Deliberately not `NormalizedPaperRead`: that carries `sections`, which holds
    the paper's extracted full text. Twenty of those in one payload is megabytes
    on the wire to fill three columns of a table.
    """

    study_type: StudyType
    methodology: dict[str, Any] | None = None
    has_full_text: bool = False
    full_text_source: str | None = None
    processing_status: ProcessingStatus

    model_config = {"from_attributes": True}


class QueryPaperRead(BaseModel):
    paper: PaperRead
    rank: int
    ranking_score: float | None
    #: Normalisation result, carried inline so a caller listing N papers does
    #: not make N follow-up requests to find out what each one is. None means
    #: there is no `normalized_papers` row — the paper has not been through the
    #: normalizer, which during a run means "not yet" and after one means it was
    #: dropped. A row whose `processing_status` is `failed` is a different
    #: state, and a reader must not collapse the two.
    normalized: NormalizedPaperSummary | None = None
    #: How many claims the extractor stored for this paper — every one of them,
    #: not the subset that reached a report section. Clustering truncates to the
    #: largest `max_clusters_per_query` clusters, so a paper can contribute real
    #: claims and appear nowhere in the report; counting from the report made
    #: those papers indistinguishable from papers nothing was extracted from.
    #: Like `normalized`, it travels with the row rather than being fetched per
    #: paper afterwards.
    claim_count: int = 0

    model_config = {"from_attributes": True}

    @classmethod
    def from_query_paper(cls, query_paper: Any, *, claim_count: int) -> "QueryPaperRead":
        """Build from a `QueryPaper` with `paper.normalized_paper` eager-loaded.

        `model_validate` cannot do this on its own: `normalized` has no matching
        attribute on `QueryPaper` — it is reached through `paper` — so validation
        would quietly fall back to the default and report every paper as
        un-normalised. That failure mode is invisible in a type check and looks
        exactly like real data loss in a UI.

        The caller must have eager-loaded the relationship. A lazy load here
        raises `MissingGreenlet` under asyncio, and were it to succeed it would
        be one query per paper inside a serialisation loop.

        `claim_count` has no default for the same reason: a caller that forgot
        it would publish a confident zero, which is the state this field exists
        to distinguish from. `paper_listing.read_query_papers` counts a whole
        list at once and is what every caller should use.
        """
        record = getattr(query_paper.paper, "normalized_paper", None)
        return cls(
            paper=PaperRead.model_validate(query_paper.paper),
            rank=query_paper.rank,
            ranking_score=query_paper.ranking_score,
            normalized=NormalizedPaperSummary.model_validate(record) if record else None,
            claim_count=claim_count,
        )
