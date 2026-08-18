"""evidence_extractor_agent — Phase 2.

Extracts atomic claims from a normalized paper and persists them. Claims are
per-paper and query-independent, so a paper that already has claims is skipped
unless re-extraction is forced.
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm_provider import get_structured_llm
from app.models.claim import Claim
from app.models.paper import NormalizedPaper, Paper, ProcessingStatus
from app.schemas.extraction import ExtractionOutput
from app.services import pdf, provenance
from app.services.prompts import EXTRACTOR_SYSTEM

logger = logging.getLogger(__name__)


def _tldr_text(paper: Paper) -> str | None:
    if isinstance(paper.tldr, dict):
        return paper.tldr.get("text")
    return None


def _context_block(paper: Paper, normalized: NormalizedPaper) -> str:
    methodology = normalized.methodology or {}
    lines = [
        f"STUDY TYPE: {normalized.study_type}",
        f"DESIGN: {methodology.get('design') or 'not reported'}",
        f"POPULATION: {methodology.get('population') or 'not reported'}",
        f"SAMPLE SIZE: {methodology.get('sample_size') or 'not reported'}",
        f"YEAR: {paper.publication_year or 'unknown'}",
    ]
    return "\n".join(lines)


async def extract_claims(
    paper: Paper,
    normalized: NormalizedPaper,
    db: AsyncSession,
    *,
    force: bool = False,
) -> list[Claim]:
    """Extract and store claims for one paper. Returns the stored claims."""
    existing = list(
        (await db.execute(select(Claim).where(Claim.paper_id == paper.id))).scalars().all()
    )
    if existing and not force:
        logger.debug("Extraction cache hit for %s (%d claims)", paper.id, len(existing))
        normalized.processing_status = ProcessingStatus.completed
        await db.commit()
        return existing

    sections = normalized.sections or {}
    text_sections = {k: v for k, v in sections.items() if isinstance(v, str) and v}
    paper_text = pdf.build_paper_text(
        title=paper.title,
        abstract=paper.abstract,
        tldr=_tldr_text(paper),
        full_text=normalized.full_text,
        sections=text_sections or None,
    )
    prompt = (
        f"{_context_block(paper, normalized)}\n\n"
        f"PAPER TEXT:\n{paper_text}"
    )

    try:
        agent = get_structured_llm(ExtractionOutput, task="extraction")
        result: ExtractionOutput = await agent.ainvoke(
            [
                SystemMessage(
                    content=EXTRACTOR_SYSTEM.format(max_claims=settings.max_claims_per_paper)
                ),
                HumanMessage(content=prompt),
            ]
        )
    except Exception as exc:  # noqa: BLE001 - one bad paper must not kill the run
        logger.warning("Extraction failed for paper %s: %s", paper.id, exc)
        normalized.processing_status = ProcessingStatus.failed
        await db.commit()
        return []

    if force and existing:
        await db.execute(delete(Claim).where(Claim.paper_id == paper.id))

    kept = [
        extracted
        for extracted in result.claims[: settings.max_claims_per_paper]
        if (extracted.claim_text or "").strip()
    ]

    # Resolved together so the paper's source text is normalized once rather
    # than once per claim, and in Python because a model cannot count characters.
    located = provenance.resolve_all(
        [extracted.supporting_quote for extracted in kept],
        normalized=normalized,
        paper=paper,
        sections=sections or None,
    )

    claims: list[Claim] = []
    for position, (extracted, source) in enumerate(zip(kept, located, strict=True), start=1):
        claim = Claim(
            paper_id=paper.id,
            claim_text=extracted.claim_text.strip(),
            evidence_type=extracted.evidence_type,
            causal_classification=extracted.causal_classification,
            methodology_details=extracted.methodology_payload(),
            sample_size=(extracted.sample_size or None) and extracted.sample_size[:100],
            effect_size=extracted.effect_size_payload(),
            confidence_score=max(0.0, min(1.0, extracted.confidence_score)),
            position_in_paper=position,
            source_quote=source.quote,
            source_origin=source.origin,
            source_section=source.section,
            source_start=source.start,
            source_end=source.end,
            source_page=source.page,
            source_match=source.match,
        )
        db.add(claim)
        claims.append(claim)

    normalized.processing_status = ProcessingStatus.completed
    await db.commit()
    for claim in claims:
        await db.refresh(claim)

    cited = sum(1 for claim in claims if claim.source_match != "none")
    logger.info(
        "Extracted %d claims from %s (%d located in source)", len(claims), paper.id, cited
    )
    return claims
