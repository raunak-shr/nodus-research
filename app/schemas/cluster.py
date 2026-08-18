from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.cluster import QualityTier
from app.schemas.claim import ClaimSourceFields


class ClaimClusterRead(BaseModel):
    id: UUID
    query_id: UUID
    central_theme: str
    consensus_summary: str | None = None
    lineage_tree: dict[str, Any] | None
    support_count: int
    neutral_count: int
    contradiction_count: int
    disagreement_drivers: list[dict[str, Any]] | None
    quality_tier: QualityTier
    quality_score: float | None = None
    quality_rationale: dict[str, Any] | None = None
    user_edited: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class ClusterClaimRead(ClaimSourceFields):
    claim_id: UUID
    paper_id: UUID
    claim_text: str
    citation: str
    stance: str
    similarity_score: float | None
    confidence_score: float
    sample_size: str | None
    # Provenance rides along so a stance chip can offer "show me the sentence"
    # without a request per claim; the full paragraph comes from claims.source.


class ClaimClusterDetail(ClaimClusterRead):
    claims: list[ClusterClaimRead] = []


class ClusterUpdate(BaseModel):
    """Phase 9 — user overrides on a cluster. Any field set marks it edited."""

    central_theme: str | None = None
    consensus_summary: str | None = None
    quality_tier: QualityTier | None = None
    disagreement_drivers: list[dict[str, Any]] | None = None


class ClusterClaimUpdate(BaseModel):
    stance: Literal["supports", "contradicts", "neutral"] = Field(
        description="Corrected stance for this claim within the cluster"
    )


class ClusterClaimAdd(BaseModel):
    claim_id: UUID
    stance: Literal["supports", "contradicts", "neutral"] = "supports"
