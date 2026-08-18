from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.paper import StudyType
from app.models.query import QueryStatus


class StructuredQuery(BaseModel):
    topic: str
    outcome_measure: str | None = None
    study_type_preferences: list[StudyType] = []
    date_range_start: int | None = None
    date_range_end: int | None = None
    # 2-4 orthogonal concepts (never synonyms of each other). Retrieval ANDs
    # these: bulk search requires every term to match, so ANDing synonyms —
    # "aerobic exercise" + "aerobic training" — returns almost nothing.
    core_concepts: list[str] = []
    search_keywords: list[str]
    clarification_needed: bool = False
    clarification_message: str | None = None


class QueryCreate(BaseModel):
    query: str


class QueryRead(BaseModel):
    id: UUID
    raw_query: str
    structured_query: dict[str, Any] | None
    status: QueryStatus
    paper_count: int
    error_message: str | None
    parent_query_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QueryWithPapersRead(QueryRead):
    papers: list[Any] = []


class QueryStatusUpdate(BaseModel):
    status: QueryStatus
    error_message: str | None = None
