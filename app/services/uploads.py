"""Papers the reader supplied, instead of papers the pipeline retrieved.

An uploaded PDF becomes an ordinary `papers` row. That is the whole design: the
rest of the pipeline — normalisation, extraction, embedding, clustering,
synthesis, the report, the chat over it, the PDF export — cannot tell the
difference, and none of it needed changing. Only two things are special.

**The identifier.** `papers.semantic_scholar_id` is the deduplication key and
cannot be null, so an upload is keyed by the sha-256 of its own bytes:
``upload:<32 hex>``. The same file uploaded twice is the same paper, and its
normalisation and claims are reused exactly as a retrieved paper's are — which
is the point of the global cache, not an exception to it. The prefix is what
tells every other reader of that column that the id addresses nothing at
Semantic Scholar.

**The full text arrives with the file.** A `normalized_papers` row is written at
upload time holding the parsed text, its page offsets and
``full_text_source="upload"``, and `normalizer.normalize_paper` reads it back
instead of going to the network. Nothing about the file is fetched, so the
arXiv fallback and the DOI resolution are skipped: for an upload the file *is*
the paper, and a "better" copy found by title search would be a different one.

Metadata is taken from the PDF and from the filename, never guessed by a model.
A title that says "Microsoft Word - final_v3.docx" is worth less than the file
the reader named, so both are considered and the more paper-like one wins.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.paper import NormalizedPaper, Paper, ProcessingStatus
from app.services import pdf
from app.services.errors import BadRequest, Unavailable

logger = logging.getLogger(__name__)

#: Every PDF starts with this. Checked because a rejected upload should say
#: "not a PDF" rather than fail three steps later inside the parser.
_MAGIC = b"%PDF-"

#: A producer string masquerading as a title. Word and LaTeX toolchains write
#: these into `/Title` constantly, and they are worse than the filename.
_JUNK_TITLE = re.compile(
    r"^(microsoft word|untitled|document\d*|manuscript|paper|preprint|"
    r"main|ms|final|draft|pdfdocument|output)\b",
    re.IGNORECASE,
)

_ID_PREFIX = "upload:"


@dataclass(frozen=True)
class UploadedPaper:
    """What the caller gets back for one accepted file."""

    paper_id: str
    #: The content hash id, so a client can recognise a re-upload of the same
    #: file as the paper it already has rather than as a second one.
    fingerprint: str
    filename: str
    title: str
    authors: list[str]
    year: int | None
    #: Pages the file declares.
    pages: int
    #: Pages the parser actually took, bounded by `pdf_max_pages`. Lower than
    #: `pages` for a long paper, and the difference is reported rather than
    #: swallowed: a reader who hands over a 45-page survey should know only its
    #: opening was read before the run spends five minutes on it.
    pages_read: int
    #: Characters of text the parser recovered. Zero means a scan with no text
    #: layer: accepted, but it will be read from its title alone, and the
    #: caller is told so rather than finding out at the end of a run.
    characters: int
    reused: bool


def is_upload(paper: Paper) -> bool:
    """Whether this paper came from a reader's file rather than from retrieval."""
    return (paper.semantic_scholar_id or "").startswith(_ID_PREFIX)


def fingerprint(data: bytes) -> str:
    return _ID_PREFIX + hashlib.sha256(data).hexdigest()[:32]


def _clean_title(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip(" .-_")
    if len(text) < 8 or len(text) > 300:
        return ""
    if _JUNK_TITLE.match(text):
        return ""
    # A title that is really a path or a filename.
    if re.search(r"\.(pdf|docx?|tex)$", text, re.IGNORECASE) or "/" in text or "\\" in text:
        return ""
    return text


def _title_from_filename(filename: str) -> str:
    stem = re.sub(r"\.pdf$", "", filename or "", flags=re.IGNORECASE)
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or "Untitled upload"


def _authors_from_metadata(value: str | None) -> list[dict[str, str]]:
    if not value:
        return []
    parts = re.split(r"\s*(?:;|,| and |&)\s*", str(value))
    names = [re.sub(r"\s+", " ", part).strip() for part in parts]
    # Two-part splits on a comma turn "Blumenthal, James" into two authors. Only
    # a fragment with no space is suspect, and dropping it loses less than
    # inventing an author called "James".
    return [{"name": name} for name in names if len(name) > 2 and " " in name][:24]


def _year_from_metadata(raw: object) -> int | None:
    match = re.search(r"(19|20)\d{2}", str(raw or ""))
    if not match:
        return None
    year = int(match.group(0))
    return year if 1800 <= year <= 2100 else None


def _pdf_metadata(data: bytes) -> tuple[str, list[dict[str, str]], int | None]:
    """Title, authors and year as the file itself declares them."""
    try:
        from pypdf import PdfReader

        info = PdfReader(io.BytesIO(data)).metadata or {}
        return (
            _clean_title(info.get("/Title")),
            _authors_from_metadata(info.get("/Author")),
            _year_from_metadata(info.get("/CreationDate") or info.get("/ModDate")),
        )
    except Exception as exc:  # noqa: BLE001 - metadata is a bonus, never a gate
        logger.info("PDF metadata unreadable: %s", exc)
        return "", [], None


async def accept_upload(
    filename: str,
    data: bytes,
    db: AsyncSession,
) -> UploadedPaper:
    """Validate one uploaded PDF and store it as a paper.

    Raises `BadRequest` with a reason a person can act on — the reader is
    standing in front of the drop zone, and "rejected" without a why is what
    makes them try the same file again.
    """
    if not settings.uploads_enabled:
        raise Unavailable("Uploading papers is disabled on this deployment.")

    if not data:
        raise BadRequest("The file is empty.", filename=filename)
    if len(data) > settings.upload_max_bytes:
        raise BadRequest(
            f"{len(data) // 1_000_000} MB is over the "
            f"{settings.upload_max_bytes // 1_000_000} MB limit for one paper.",
            filename=filename,
        )
    if not data.startswith(_MAGIC):
        raise BadRequest("Not a PDF — the file does not start with %PDF-.", filename=filename)

    pages = pdf.declared_page_count(data)
    if not pages:
        raise BadRequest(
            "The PDF could not be opened — it may be corrupt or password-protected.",
            filename=filename,
        )
    if pages > settings.upload_max_pages:
        raise BadRequest(
            f"{pages} pages — this is longer than a paper "
            f"(the limit is {settings.upload_max_pages}).",
            filename=filename,
            pages=pages,
        )

    ident = fingerprint(data)

    existing = (
        await db.execute(select(Paper).where(Paper.semantic_scholar_id == ident))
    ).scalar_one_or_none()
    if existing is not None:
        normalized = (
            await db.execute(select(NormalizedPaper).where(NormalizedPaper.paper_id == existing.id))
        ).scalar_one_or_none()
        return UploadedPaper(
            paper_id=str(existing.id),
            fingerprint=ident,
            filename=filename,
            title=existing.title,
            authors=[str(a.get("name", "")) for a in (existing.authors or [])],
            year=existing.publication_year,
            pages=pages,
            pages_read=len((normalized.page_offsets if normalized else None) or []),
            characters=len((normalized.full_text if normalized else None) or ""),
            reused=True,
        )

    document = pdf.parse_pdf_bytes(data, source="upload")
    meta_title, meta_authors, meta_year = _pdf_metadata(data)
    title = meta_title or _title_from_filename(filename)

    paper = Paper(
        semantic_scholar_id=ident,
        title=title[:1000],
        abstract=None,
        authors=meta_authors,
        publication_year=meta_year,
        # Kept so the paper reads as what it is everywhere it is listed, rather
        # than as a journal article with a missing venue.
        venue="Uploaded by reader",
        citation_count=0,
        influential_citation_count=0,
        fields_of_study=[],
        open_access_pdf_url=None,
        tldr=None,
        doi=None,
        arxiv_id=None,
    )
    db.add(paper)
    await db.flush()

    # Written now, before any run refers to it: this row is how the text reaches
    # the normalizer without a fetch. `pending`, not `completed` — the LLM has
    # not read it yet, and claiming otherwise would skip normalisation entirely.
    db.add(
        NormalizedPaper(
            paper_id=paper.id,
            full_text=document.text if document else None,
            page_offsets=(document.page_offsets if document else None) or None,
            full_text_source="upload",
            sections=pdf.split_sections(document.text) if document else None,
            processing_status=ProcessingStatus.pending,
        )
    )
    await db.commit()

    logger.info(
        "Accepted upload %s as paper %s (%d pages, %d read, %d chars)",
        filename,
        paper.id,
        pages,
        document.page_count if document else 0,
        len(document.text) if document else 0,
    )
    return UploadedPaper(
        paper_id=str(paper.id),
        fingerprint=ident,
        filename=filename,
        title=title,
        authors=[str(a.get("name", "")) for a in meta_authors],
        year=meta_year,
        pages=pages,
        pages_read=document.page_count if document else 0,
        characters=len(document.text) if document else 0,
        reused=False,
    )


async def resolve_for_run(paper_ids: list[str], db: AsyncSession) -> list[Paper]:
    """The uploaded papers a run was asked to use, in the order given.

    Every id must resolve to an upload. A retrieved paper's id passed here would
    quietly build a corpus the reader never chose, so it is refused by name.
    """
    if len(paper_ids) < settings.upload_min_papers:
        raise BadRequest(
            f"A run over uploaded papers needs at least {settings.upload_min_papers} of them — "
            "clustering compares claims across papers, and there is nothing to compare in one.",
            given=len(paper_ids),
        )
    if len(paper_ids) > settings.upload_max_papers:
        raise BadRequest(
            f"{len(paper_ids)} papers — the limit is {settings.upload_max_papers}.",
            given=len(paper_ids),
        )

    rows = (await db.execute(select(Paper).where(Paper.id.in_(paper_ids)))).scalars().all()
    by_id = {str(row.id): row for row in rows}

    missing = [pid for pid in paper_ids if pid not in by_id]
    if missing:
        raise BadRequest(
            "Some uploaded papers are no longer stored — upload them again.",
            missing=missing,
        )

    ordered = [by_id[pid] for pid in paper_ids]
    foreign = [p.title for p in ordered if not is_upload(p)]
    if foreign:
        raise BadRequest(
            "Only uploaded papers can make up a custom corpus.",
            papers=foreign[:5],
        )
    return ordered
