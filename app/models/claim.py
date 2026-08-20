import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class EvidenceType(enum.StrEnum):
    empirical = "empirical"
    theoretical = "theoretical"
    anecdotal = "anecdotal"
    meta_analytic = "meta_analytic"


class CausalClassification(enum.StrEnum):
    causal = "causal"
    correlational = "correlational"
    speculative = "speculative"
    descriptive = "descriptive"


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_type: Mapped[EvidenceType] = mapped_column(
        Enum(EvidenceType, name="evidence_type"), nullable=False
    )
    causal_classification: Mapped[CausalClassification] = mapped_column(
        Enum(CausalClassification, name="causal_classification"), nullable=False
    )
    methodology_details: Mapped[dict | None] = mapped_column(JSONB)
    sample_size: Mapped[str | None] = mapped_column(String(100))
    effect_size: Mapped[dict | None] = mapped_column(JSONB)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    position_in_paper: Mapped[int | None] = mapped_column(Integer)

    # Provenance — where in the paper this claim came from. Offsets index the
    # paper's canonical source text, which `app/services/provenance.py` defines
    # as parsed full text when a PDF was available and the abstract otherwise;
    # they are meaningless without it. `source_match` records how the quote was
    # located ("exact", "normalized", "fuzzy") or that it was not ("none"), so a
    # citation chip can say "verified" or "approximate" instead of guessing.
    source_quote: Mapped[str | None] = mapped_column(Text)
    # Which text the quote was resolved against: "full_text", "abstract", or
    # NULL when there was no quote or no text. A reader must be able to tell a
    # sentence found in the paper body from one found only in the abstract.
    source_origin: Mapped[str | None] = mapped_column(String(20))
    source_section: Mapped[str | None] = mapped_column(String(50))
    source_start: Mapped[int | None] = mapped_column(Integer)
    source_end: Mapped[int | None] = mapped_column(Integer)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_match: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    paper: Mapped["Paper"] = relationship("Paper", back_populates="claims")  # noqa: F821
    embedding: Mapped["ClaimEmbedding | None"] = relationship(
        "ClaimEmbedding", back_populates="claim", uselist=False, cascade="all, delete-orphan"
    )
    cluster_claims: Mapped[list["ClusterClaim"]] = relationship(  # noqa: F821
        "ClusterClaim", back_populates="claim", cascade="all, delete-orphan"
    )


class ClaimEmbedding(Base):
    __tablename__ = "claim_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False, default="nomic-embed-text")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    claim: Mapped["Claim"] = relationship("Claim", back_populates="embedding")
