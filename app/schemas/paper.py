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

    model_config = {"from_attributes": True}

    @classmethod
    def from_query_paper(cls, query_paper: Any) -> "QueryPaperRead":
        """Build from a `QueryPaper` with `paper.normalized_paper` eager-loaded.

        `model_validate` cannot do this on its own: `normalized` has no matching
        attribute on `QueryPaper` — it is reached through `paper` — so validation
        would quietly fall back to the default and report every paper as
        un-normalised. That failure mode is invisible in a type check and looks
        exactly like real data loss in a UI.

        The caller must have eager-loaded the relationship. A lazy load here
        raises `MissingGreenlet` under asyncio, and were it to succeed it would
        be one query per paper inside a serialisation loop.
        """
        record = getattr(query_paper.paper, "normalized_paper", None)
        return cls(
            paper=PaperRead.model_validate(query_paper.paper),
            rank=query_paper.rank,
            ranking_score=query_paper.ranking_score,
            normalized=NormalizedPaperSummary.model_validate(record) if record else None,
        )
