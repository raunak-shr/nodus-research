"""paper_normalizer_agent — Phase 2.

Turns a retrieved paper into a NormalizedPaper row: full text when an open
access PDF exists, parsed sections, study-type classification and methodology.
Already-normalized papers are reused (papers are global, so this cache pays off
across queries).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_provider import get_llm_name, get_structured_llm
from app.models.paper import NormalizedPaper, Paper, ProcessingStatus
from app.schemas.extraction import NormalizationOutput
from app.services import arxiv, pdf
from app.services.prompts import NORMALIZER_SYSTEM

logger = logging.getLogger(__name__)


def _tldr_text(paper: Paper) -> str | None:
    if isinstance(paper.tldr, dict):
        return paper.tldr.get("text")
    return None


async def normalize_paper(
    paper: Paper,
    db: AsyncSession,
    *,
    force: bool = False,
) -> NormalizedPaper:
    """Normalize one paper, reusing a previous successful run unless `force`."""
    existing = (
        await db.execute(select(NormalizedPaper).where(NormalizedPaper.paper_id == paper.id))
    ).scalar_one_or_none()

    if existing and existing.processing_status == ProcessingStatus.completed and not force:
        logger.debug("Normalization cache hit for %s", paper.id)
        return existing

    record = existing or NormalizedPaper(paper_id=paper.id)
    record.processing_status = ProcessingStatus.normalizing
    if existing is None:
        db.add(record)
    await db.commit()

    # The DOI is a second way in: Semantic Scholar supplies no PDF url for more
    # than half the papers a query retrieves, and the publisher page a DOI
    # resolves to usually advertises the file anyway.
    document = await pdf.fetch_pdf_document(paper.open_access_pdf_url, doi=paper.doi)
    if pdf.is_thin(document):
        # Nothing, or a paywall's one-page "abstract only" file. Either way this
        # paper is about to be read from its abstract, so a preprint on arXiv is
        # worth the throttled request. Kept only if it is actually longer: the
        # fallback exists to add full text, never to trade some away.
        replacement = await arxiv.fetch_document(
            arxiv_id=paper.arxiv_id, title=paper.title, authors=paper.authors
        )
        if replacement and (document is None or len(replacement.text) > len(document.text)):
            document = replacement
    full_text = document.text if document else None
    # Page starts are only knowable at parse time; nothing downstream can
    # reconstruct them without fetching the PDF again.
    page_offsets = document.page_offsets if document else None
    sections = pdf.split_sections(full_text) if full_text else {}
    paper_text = pdf.build_paper_text(
        title=paper.title,
        abstract=paper.abstract,
        tldr=_tldr_text(paper),
        full_text=full_text,
        sections=sections or None,
    )

    try:
        agent = get_structured_llm(NormalizationOutput, task="extraction")
        result: NormalizationOutput = await agent.ainvoke(
            [SystemMessage(content=NORMALIZER_SYSTEM), HumanMessage(content=paper_text)]
        )
    except Exception as exc:  # noqa: BLE001 - one bad paper must not kill the run
        logger.warning("Normalization failed for paper %s: %s", paper.id, exc)
        record.processing_status = ProcessingStatus.failed
        record.full_text = full_text
        record.page_offsets = page_offsets or None
        record.full_text_source = document.source if document else None
        record.sections = sections or None
        await db.commit()
        return record

    merged_sections: dict[str, str | None] = dict(sections)
    for key, value in result.sections_payload().items():
        merged_sections.setdefault(key, value)

    record.full_text = full_text
    record.page_offsets = page_offsets or None
    record.full_text_source = document.source if document else None
    record.sections = merged_sections or None
    record.study_type = result.study_type
    record.methodology = result.methodology_payload()
    record.llm_model_used = get_llm_name()
    record.processed_at = datetime.now(UTC)
    record.processing_status = ProcessingStatus.extracting
    await db.commit()
    await db.refresh(record)

    logger.info(
        "Normalized %s as %s (full_text=%s, source=%s)",
        paper.id,
        record.study_type,
        "yes" if full_text else "no",
        document.source if document else "none",
    )
    return record


async def get_normalized(paper_id: UUID, db: AsyncSession) -> NormalizedPaper | None:
    return (
        await db.execute(select(NormalizedPaper).where(NormalizedPaper.paper_id == paper_id))
    ).scalar_one_or_none()
