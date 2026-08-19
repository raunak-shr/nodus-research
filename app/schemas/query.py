from datetime import datetime
from typing import Any, Literal
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


#: What the assessor may return. `unassessed` is not among them: the model does
#: not get to say its own check did not run.
AssessedVerdict = Literal["ready", "workable", "unsuitable"]
#: What the API returns, which adds the one verdict only the server can reach.
Verdict = Literal["ready", "workable", "unsuitable", "unassessed"]


class QueryAssessment(BaseModel):
    """Assessor output. Flat, with numbered suggestions rather than a list,
    because strict JSON-schema decoding is markedly more reliable on scalars."""

    verdict: AssessedVerdict
    reason: str
    suggestion_1: str | None = None
    suggestion_2: str | None = None
    suggestion_3: str | None = None

    def suggestions(self) -> list[str]:
        candidates = [self.suggestion_1, self.suggestion_2, self.suggestion_3]
        return [text.strip() for text in candidates if text and text.strip()]


class QueryInterpret(BaseModel):
    query: str


class QueryInterpretation(BaseModel):
    """What the Interpret button gets back: how the question was read, and
    whether running it is worth five minutes and twenty papers."""

    question: str
    verdict: Verdict
    #: True only for `ready`. Everything else still runs — the pipeline refuses
    #: nothing — but the caller is told what they will get first.
    worth_running: bool
    reason: str
    #: Sharper questions to run instead. Empty when the question is ready, and
    #: also empty when the text carried no subject worth suggesting against.
    suggestions: list[str] = []
    structured_query: StructuredQuery


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
