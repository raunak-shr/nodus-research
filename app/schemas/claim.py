from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.claim import CausalClassification, EvidenceType


class ClaimRead(BaseModel):
    id: UUID
    paper_id: UUID
    claim_text: str
    evidence_type: EvidenceType
    causal_classification: CausalClassification
    methodology_details: dict[str, Any] | None
    sample_size: str | None
    effect_size: dict[str, Any] | None
    confidence_score: float = Field(ge=0.0, le=1.0)
    position_in_paper: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
