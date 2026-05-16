from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.query import QueryStatus


class QueryCreate(BaseModel):
    raw_query: str


class QueryRead(BaseModel):
    id: UUID
    raw_query: str
    structured_query: dict[str, Any] | None
    status: QueryStatus
    paper_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QueryStatusUpdate(BaseModel):
    status: QueryStatus
    error_message: str | None = None
