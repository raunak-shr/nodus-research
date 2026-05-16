import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class QueryStatus(enum.StrEnum):
    pending = "pending"
    structuring = "structuring"
    retrieving = "retrieving"
    processing = "processing"
    clustering = "clustering"
    completed = "completed"
    failed = "failed"


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    raw_query: Mapped[str] = mapped_column(Text, nullable=False)
    structured_query: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[QueryStatus] = mapped_column(
        Enum(QueryStatus, name="query_status"),
        nullable=False,
        default=QueryStatus.pending,
    )
    paper_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    query_papers: Mapped[list["QueryPaper"]] = relationship(  # noqa: F821
        "QueryPaper", back_populates="query", cascade="all, delete-orphan"
    )
    clusters: Mapped[list["ClaimCluster"]] = relationship(  # noqa: F821
        "ClaimCluster", back_populates="query", cascade="all, delete-orphan"
    )
