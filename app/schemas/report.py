from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ReportRead(BaseModel):
    id: UUID
    query_id: UUID
    title: str
    executive_summary: str | None
    key_findings: list[str] | None
    open_questions: list[str] | None
    sections: list[dict[str, Any]] | None
    llm_model_used: str | None
    user_edited: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReportUpdate(BaseModel):
    """Phase 9 — every level of the report is user-editable."""

    title: str | None = None
    executive_summary: str | None = None
    key_findings: list[str] | None = None
    open_questions: list[str] | None = None
    sections: list[dict[str, Any]] | None = None


class SectionNarrativeUpdate(BaseModel):
    """Edit a single report section without resending the whole document."""

    heading: str | None = None
    narrative: str | None = None
    caveats: list[str] | None = None


class FollowUpCreate(BaseModel):
    """Phase 10 — a follow-up question scoped to a previous query."""

    query: str = Field(min_length=3, description="The follow-up research question")
