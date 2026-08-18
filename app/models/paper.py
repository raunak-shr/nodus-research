import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class StudyType(enum.StrEnum):
    rct = "rct"
    observational = "observational"
    meta_analysis = "meta_analysis"
    systematic_review = "systematic_review"
    case_study = "case_study"
    cohort = "cohort"
    cross_sectional = "cross_sectional"
    qualitative = "qualitative"
    review = "review"
    preprint = "preprint"
    unknown = "unknown"


class ProcessingStatus(enum.StrEnum):
    pending = "pending"
    normalizing = "normalizing"
    extracting = "extracting"
    completed = "completed"
    failed = "failed"


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    semantic_scholar_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    doi: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(String(500))
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    influential_citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_of_study: Mapped[list] = mapped_column(JSONB, default=list)
    open_access_pdf_url: Mapped[str | None] = mapped_column(String(2048))
    tldr: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    query_papers: Mapped[list["QueryPaper"]] = relationship(
        "QueryPaper", back_populates="paper"
    )
    normalized_paper: Mapped["NormalizedPaper | None"] = relationship(
        "NormalizedPaper", back_populates="paper", uselist=False
    )
    claims: Mapped[list["Claim"]] = relationship(  # noqa: F821
        "Claim", back_populates="paper", cascade="all, delete-orphan"
    )


class QueryPaper(Base):
    __tablename__ = "query_papers"

    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("queries.id", ondelete="CASCADE"),
        primary_key=True,
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    ranking_score: Mapped[float | None] = mapped_column(Float)

    query: Mapped["Query"] = relationship("Query", back_populates="query_papers")  # noqa: F821
    paper: Mapped["Paper"] = relationship("Paper", back_populates="query_papers")


class NormalizedPaper(Base):
    __tablename__ = "normalized_papers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    full_text: Mapped[str | None] = mapped_column(Text)
    sections: Mapped[dict | None] = mapped_column(JSONB)
    study_type: Mapped[StudyType] = mapped_column(
        Enum(StudyType, name="study_type"), nullable=False, default=StudyType.unknown
    )
    methodology: Mapped[dict | None] = mapped_column(JSONB)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, name="processing_status"),
        nullable=False,
        default=ProcessingStatus.pending,
    )
    llm_model_used: Mapped[str | None] = mapped_column(String(100))
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    paper: Mapped["Paper"] = relationship("Paper", back_populates="normalized_paper")

    @property
    def has_full_text(self) -> bool:
        """Whether an open-access PDF was parsed, as opposed to abstract-only."""
        return bool(self.full_text)
