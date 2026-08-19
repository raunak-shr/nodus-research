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


class QueryPaperRead(BaseModel):
    paper: PaperRead
    rank: int
    ranking_score: float | None

    model_config = {"from_attributes": True}
