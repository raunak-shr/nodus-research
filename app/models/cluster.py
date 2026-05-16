import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class QualityTier(enum.StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    unrated = "unrated"


class ClaimCluster(Base):
    __tablename__ = "claim_clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("queries.id", ondelete="CASCADE"), nullable=False
    )
    central_theme: Mapped[str] = mapped_column(Text, nullable=False)
    lineage_tree: Mapped[dict | None] = mapped_column(JSONB)
    support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    neutral_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contradiction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disagreement_drivers: Mapped[list | None] = mapped_column(JSONB)
    quality_tier: Mapped[QualityTier] = mapped_column(
        Enum(QualityTier, name="quality_tier"), nullable=False, default=QualityTier.unrated
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    query: Mapped["Query"] = relationship("Query", back_populates="clusters")  # noqa: F821
    cluster_claims: Mapped[list["ClusterClaim"]] = relationship(
        "ClusterClaim", back_populates="cluster", cascade="all, delete-orphan"
    )


class ClusterClaim(Base):
    __tablename__ = "cluster_claims"

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claim_clusters.id", ondelete="CASCADE"),
        primary_key=True,
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        primary_key=True,
    )
    similarity_score: Mapped[float | None] = mapped_column(Float)
    stance: Mapped[str] = mapped_column(String(20), nullable=False, default="supports")

    cluster: Mapped["ClaimCluster"] = relationship("ClaimCluster", back_populates="cluster_claims")
    claim: Mapped["Claim"] = relationship("Claim", back_populates="cluster_claims")  # noqa: F821
