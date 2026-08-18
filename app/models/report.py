import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Report(Base):
    """Phase 8 synthesizer output — one report per query, regenerable in place."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("queries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    executive_summary: Mapped[str | None] = mapped_column(Text)
    key_findings: Mapped[list | None] = mapped_column(JSONB)
    open_questions: Mapped[list | None] = mapped_column(JSONB)
    # sections: [{cluster_id, heading, narrative, caveats, quality_tier,
    #             stance_counts, lineage, disagreement_drivers, claims}]
    sections: Mapped[list | None] = mapped_column(JSONB)
    llm_model_used: Mapped[str | None] = mapped_column(String(100))
    user_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    query: Mapped["Query"] = relationship("Query", back_populates="report")  # noqa: F821
