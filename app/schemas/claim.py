from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.claim import CausalClassification, EvidenceType

#: How a claim's supporting quote was located in the paper's source text.
#: "none" is an ordinary outcome — abstract-only papers and truncated PDFs
#: produce claims with nowhere to point — so a client must handle it as a state
#: rather than an error. See `app/services/provenance.py`.
SourceMatch = Literal["exact", "normalized", "fuzzy", "none"]

#: Which text a quote was resolved against. `abstract` means the paper body was
#: never retrieved, so there is no page and no paragraph to show.
SourceOrigin = Literal["full_text", "abstract"]


class ClaimSourceFields(BaseModel):
    """The provenance columns, flat, exactly as the claims table stores them.

    Flat rather than nested so `model_validate(claim)` keeps working straight off
    the ORM row, and so a citation chip can decide what to render from these
    alone without a second request.
    """

    source_match: SourceMatch = "none"
    source_quote: str | None = None
    #: A client must branch on this *before* `source_match`: an abstract-only
    #: quote can match exactly and still not be verified against the paper body.
    source_origin: SourceOrigin | None = None
    source_section: str | None = None
    source_page: int | None = None
    source_start: int | None = None
    source_end: int | None = None


class ClaimRead(ClaimSourceFields):
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


class ClaimSourceRead(BaseModel):
    """Everything needed to show a reader the text a claim came from.

    `highlight_start`/`highlight_end` are relative to `context`, so a client can
    highlight the quote inside the paragraph it displays without recomputing
    offsets against a source text it never receives.
    """

    claim_id: UUID
    paper_id: UUID
    paper_title: str
    citation: str
    claim_text: str
    #: False when there is nothing to point at. The reason is in `match` and
    #: `origin`: no open-access PDF, text truncated, or the quote drifted too far
    #: from the paper to be located.
    available: bool
    match: SourceMatch
    origin: SourceOrigin | None = None
    #: Why a reader is seeing less than a verified passage, in plain words.
    #: None when the quote was found exactly in the paper body and needs no caveat.
    reason: str | None = None
    quote: str | None = None
    section: str | None = None
    page: int | None = None
    start: int | None = None
    end: int | None = None
    context: str | None = None
    context_start: int | None = None
    highlight_start: int | None = None
    highlight_end: int | None = None
    pdf_url: str | None = None
