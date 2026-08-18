"""LLM structured-output schemas for Stage 3 (cross-paper analysis + synthesis)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Stance = Literal["supports", "contradicts", "neutral"]

DriverType = Literal[
    "methodology",
    "population",
    "metric_definition",
    "temporal",
    "sample_size",
    "analysis",
    "publication_bias",
    "other",
]


class ClaimStance(BaseModel):
    """Where one claim sits relative to the cluster's central theme."""

    claim_index: int = Field(description="1-based index of the claim in the provided list")
    stance: Stance = Field(description="Position relative to the central theme")
    reason: str | None = Field(default=None, description="One clause explaining the stance")


class DisagreementDriver(BaseModel):
    """Axis 2: a concrete reason papers in this cluster disagree."""

    type: DriverType = Field(description="Category of the disagreement driver")
    description: str = Field(description="What specifically differs, naming the papers involved")


class ClusterAnalysis(BaseModel):
    """cross_paper_analysis_agent output — one per claim cluster."""

    central_theme: str = Field(description="The shared assertion, as a single declarative sentence")
    consensus_summary: str = Field(
        description="2-3 sentences: what the papers agree on and where they diverge"
    )
    stances: list[ClaimStance] = Field(description="One entry per claim provided")
    disagreement_drivers: list[DisagreementDriver] = Field(
        description="Empty list when the claims genuinely agree"
    )


class ClusterNarrative(BaseModel):
    """synthesizer_agent output — the prose for one report section."""

    heading: str = Field(description="Short section heading, under 12 words")
    narrative: str = Field(
        description="2-4 paragraphs weighing the evidence, citing papers as [Author, Year]"
    )
    caveats: list[str] = Field(description="Explicit caveats a skeptical reviewer would raise")


class ReportSummary(BaseModel):
    """synthesizer_agent output — the report's front matter."""

    title: str = Field(description="Report title, under 15 words")
    executive_summary: str = Field(
        description="3-5 sentences answering the research question with hedges where warranted"
    )
    key_findings: list[str] = Field(description="3-6 bullet findings, each one sentence")
    open_questions: list[str] = Field(
        description="2-4 questions the retrieved evidence cannot settle"
    )
