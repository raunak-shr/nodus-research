"""LLM structured-output schemas for Stage 2 (normalization + extraction).

Fields are deliberately flat: strict JSON-schema decoding (Azure/OpenAI) is far
more reliable with scalars than with nested objects, so nested JSONB payloads
(`methodology`, `effect_size`, …) are assembled from these on the Python side.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.claim import CausalClassification, EvidenceType
from app.models.paper import StudyType


class NormalizationOutput(BaseModel):
    """paper_normalizer_agent output — one per paper."""

    study_type: StudyType = Field(description="Best-fitting study design category")
    design: str | None = Field(default=None, description="Concrete design, e.g. 'double-blind RCT'")
    sample_size: str | None = Field(
        default=None, description="Sample size as reported, e.g. 'n=1200'"
    )
    population: str | None = Field(default=None, description="Population studied")
    duration: str | None = Field(default=None, description="Study duration or follow-up period")
    setting: str | None = Field(
        default=None, description="Setting, e.g. 'multi-center, 3 hospitals'"
    )
    objective: str | None = Field(default=None, description="Stated research objective")
    methods_summary: str | None = Field(default=None, description="Methods in 2-4 sentences")
    results_summary: str | None = Field(default=None, description="Key results in 2-4 sentences")
    conclusion_summary: str | None = Field(default=None, description="Authors' conclusion")
    limitations: str | None = Field(default=None, description="Limitations the authors acknowledge")

    def methodology_payload(self) -> dict[str, Any]:
        return {
            "design": self.design,
            "sample_size": self.sample_size,
            "population": self.population,
            "duration": self.duration,
            "setting": self.setting,
            "objective": self.objective,
            "limitations": self.limitations,
        }

    def sections_payload(self) -> dict[str, Any]:
        return {
            "methods": self.methods_summary,
            "results": self.results_summary,
            "conclusion": self.conclusion_summary,
        }


class ExtractedClaim(BaseModel):
    """A single atomic evidence unit from evidence_extractor_agent."""

    claim_text: str = Field(description="One self-contained factual claim, quoted or paraphrased")
    evidence_type: EvidenceType = Field(description="What kind of evidence backs the claim")
    causal_classification: CausalClassification = Field(
        description="Strength of the causal language the paper actually uses"
    )
    study_design: str | None = Field(default=None, description="Design behind this specific claim")
    statistical_test: str | None = Field(default=None, description="Test used, if reported")
    p_value: float | None = Field(default=None, description="p-value if reported, else null")
    confidence_interval: str | None = Field(default=None, description="e.g. '95% CI [1.2, 3.4]'")
    sample_size: str | None = Field(default=None, description="Sample backing this claim")
    effect_metric: str | None = Field(default=None, description="e.g. 'odds ratio', 'Cohen d'")
    effect_value: float | None = Field(default=None, description="Numeric effect size, else null")
    effect_ci_lower: float | None = Field(default=None, description="Lower CI bound, else null")
    effect_ci_upper: float | None = Field(default=None, description="Upper CI bound, else null")
    confidence_score: float = Field(
        default=0.5, description="0.0-1.0 confidence that this extraction is faithful to the paper"
    )
    supporting_quote: str | None = Field(
        default=None,
        description=(
            "The exact sentence or two from the supplied text that this claim came "
            "from, copied character for character. Never paraphrased, never "
            "stitched together from separate places. Null if no single span "
            "supports it."
        ),
    )

    def methodology_payload(self) -> dict[str, Any] | None:
        payload = {
            "study_design": self.study_design,
            "statistical_test": self.statistical_test,
            "p_value": self.p_value,
            "confidence_interval": self.confidence_interval,
        }
        return payload if any(v is not None for v in payload.values()) else None

    def effect_size_payload(self) -> dict[str, Any] | None:
        payload = {
            "metric": self.effect_metric,
            "value": self.effect_value,
            "ci_lower": self.effect_ci_lower,
            "ci_upper": self.effect_ci_upper,
        }
        return payload if any(v is not None for v in payload.values()) else None


class ExtractionOutput(BaseModel):
    """evidence_extractor_agent output — all claims for one paper."""

    claims: list[ExtractedClaim] = Field(
        description="Atomic claims, ordered as they appear in the paper"
    )
