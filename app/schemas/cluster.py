from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.cluster import QualityTier


class ClaimClusterRead(BaseModel):
    id: UUID
    query_id: UUID
    central_theme: str
    lineage_tree: dict[str, Any] | None
    support_count: int
    neutral_count: int
    contradiction_count: int
    disagreement_drivers: list[dict[str, Any]] | None
    quality_tier: QualityTier
    created_at: datetime

    model_config = {"from_attributes": True}
