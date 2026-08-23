"""Accepting a reader's own PDFs as papers.

Hermetic: the only real thing here is pypdf, fed PDFs built in memory. Nothing
reaches the network or the database — the database is a stub, because what these
tests are about is the *decision* to accept a file and what is written when one
is accepted, not the writing itself.
"""

import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.paper import NormalizedPaper, Paper, ProcessingStatus
from app.services import uploads
from app.services.errors import BadRequest, Unavailable


def _pdf(pages: int = 3) -> bytes:
    """A real PDF with a known page count and real text on every page.

    Text, not blank pages: `_extract_document` returns None for a document that
    parses to nothing, so a blank PDF exercises the scanned-page path rather
    than the ordinary one — and `pages_read` would always come back zero.
    """
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(width=300, height=300)
        stream = DecodedStreamObject()
        stream.set_data(
            f"BT /F1 12 Tf 20 200 Td (Results page {index + 1} of the trial.) Tj ET".encode()
        )
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _blank_pdf(pages: int = 2) -> bytes:
    """A PDF with pages but no text layer — a scan, as far as the parser knows."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class _StubDb:
    """Enough AsyncSession for `accept_upload`: one lookup, then writes."""

    def __init__(self, existing=None, normalized=None) -> None:
        self._results = [existing, normalized]
        self.added: list[object] = []
        self.commits = 0

    async def execute(self, *args, **kwargs):
        value = self._results.pop(0) if self._results else None
        return SimpleNamespace(scalar_one_or_none=lambda: value)

    def add(self, obj) -> None:
        self.added.append(obj)
        if isinstance(obj, Paper) and obj.id is None:
            obj.id = "paper-1"

    async def flush(self) -> None:
        # The real session assigns the primary key here; the stub stands in for
        # it so `accept_upload` has an id to hand back.
        for obj in self.added:
            if isinstance(obj, Paper) and getattr(obj, "id", None) is None:
                obj.id = "paper-1"

    async def commit(self) -> None:
        self.commits += 1


# -- the identifier ---------------------------------------------------------


def test_the_id_is_the_hash_of_the_bytes_and_fits_the_column():
    data = _pdf()
    ident = uploads.fingerprint(data)

    assert ident.startswith("upload:")
    # `papers.semantic_scholar_id` is String(40). An id that does not fit is an
    # insert that fails on the first real upload rather than in a test.
    assert len(ident) <= 40
    assert uploads.fingerprint(data) == ident
    assert uploads.fingerprint(_pdf(pages=4)) != ident


def test_an_upload_is_recognisable_as_one():
    assert uploads.is_upload(Paper(semantic_scholar_id=uploads.fingerprint(b"x")))
    assert not uploads.is_upload(Paper(semantic_scholar_id="649def34f8be52c8b66281af283ae"))
    # Never crashes on a half-built row: this is called while listing papers.
    assert not uploads.is_upload(Paper(semantic_scholar_id=None))


# -- refusals ---------------------------------------------------------------


async def test_a_file_that_is_not_a_pdf_is_refused_by_its_first_bytes():
    with pytest.raises(BadRequest) as caught:
        await uploads.accept_upload("notes.pdf", b"PK\x03\x04 this is a zip", _StubDb())
    assert "Not a PDF" in caught.value.message


async def test_a_long_paper_is_accepted_and_its_truncation_reported():
    """The page cap asks "is this a paper", not "how much will be read".

    `pdf_max_pages` is the read budget and applies to an upload exactly as it
    applies to a retrieved paper, so refusing a 15-page conference paper the
    pipeline would happily take from Semantic Scholar would be incoherent — and
    it refused ten of fourteen papers in a real arXiv folder. What matters is
    that the truncation is *reported*, which is why `pages_read` exists.
    """
    long_paper = settings.pdf_max_pages + 20
    accepted = await uploads.accept_upload("survey.pdf", _pdf(pages=long_paper), _StubDb())

    assert accepted.pages == long_paper
    assert accepted.pages_read == settings.pdf_max_pages
    assert accepted.pages_read < accepted.pages


async def test_something_longer_than_any_paper_is_still_refused():
    data = _pdf(pages=settings.upload_max_pages + 5)

    with pytest.raises(BadRequest) as caught:
        await uploads.accept_upload("a-whole-book.pdf", data, _StubDb())

    assert str(settings.upload_max_pages) in caught.value.message
    assert caught.value.detail["pages"] == settings.upload_max_pages + 5


async def test_an_oversized_file_is_refused_before_it_is_parsed():
    with patch.object(settings, "upload_max_bytes", 500):
        with pytest.raises(BadRequest):
            await uploads.accept_upload("big.pdf", _pdf(), _StubDb())


async def test_an_unopenable_file_is_refused_with_a_reason():
    with pytest.raises(BadRequest) as caught:
        await uploads.accept_upload("broken.pdf", b"%PDF-1.7\nnot really", _StubDb())
    assert "could not be opened" in caught.value.message


async def test_uploads_can_be_switched_off():
    with patch.object(settings, "uploads_enabled", False):
        with pytest.raises(Unavailable):
            await uploads.accept_upload("a.pdf", _pdf(), _StubDb())


# -- what acceptance writes -------------------------------------------------


async def test_an_accepted_paper_carries_its_text_so_nothing_is_fetched_later():
    """The whole reason the normalizer can leave an upload alone.

    `full_text_source="upload"` is the flag it reads; without it the pipeline
    would go looking on arXiv for a paper that was never published.
    """
    db = _StubDb()
    accepted = await uploads.accept_upload("blumenthal_2007.pdf", _pdf(), db)

    normalized = next(row for row in db.added if isinstance(row, NormalizedPaper))
    assert normalized.full_text_source == "upload"
    assert normalized.processing_status == ProcessingStatus.pending
    assert accepted.pages == 3
    # Short enough that nothing was left out — the two numbers agree.
    assert accepted.pages_read == 3
    assert accepted.reused is False


async def test_a_scan_with_no_text_layer_is_accepted_and_says_so():
    """Accepted, because refusing it would be refusing a real paper.

    But `characters: 0` is the caller's warning that there is nothing in it to
    extract from — said at upload, not discovered at the end of a five-minute
    run.
    """
    accepted = await uploads.accept_upload("scan.pdf", _blank_pdf(4), _StubDb())

    assert accepted.pages == 4
    assert accepted.characters == 0
    assert accepted.pages_read == 0


async def test_the_filename_names_the_paper_when_the_pdf_does_not():
    db = _StubDb()
    accepted = await uploads.accept_upload("blumenthal_2007_exercise-depression.pdf", _pdf(), db)
    assert accepted.title == "blumenthal 2007 exercise depression"


async def test_the_same_file_twice_is_one_paper():
    """Deduplication is the point of hashing the bytes.

    A reader who drops the same PDF twice, or reloads and drops it again, has
    one paper — and it keeps the normalisation and claims the first upload paid
    for, exactly as a re-retrieved paper does.
    """
    existing = Paper(
        id="paper-1",
        semantic_scholar_id=uploads.fingerprint(_pdf()),
        title="Already here",
        authors=[{"name": "A Researcher"}],
        publication_year=2007,
    )
    db = _StubDb(existing=existing, normalized=NormalizedPaper(full_text="x" * 40))

    accepted = await uploads.accept_upload("again.pdf", _pdf(), db)

    assert accepted.reused is True
    assert accepted.paper_id == "paper-1"
    assert accepted.characters == 40
    assert db.added == []


# -- metadata ---------------------------------------------------------------


def test_a_producer_string_is_not_a_title():
    assert uploads._clean_title("Microsoft Word - final_v3.docx") == ""
    assert uploads._clean_title("untitled") == ""
    assert uploads._clean_title("C:/papers/draft.pdf") == ""
    assert (
        uploads._clean_title("Exercise and Pharmacotherapy in Major Depression")
        == "Exercise and Pharmacotherapy in Major Depression"
    )


def test_author_fragments_without_a_forename_are_dropped():
    """ "Blumenthal, James" splits into two on the comma, and one of them is not
    a person. Losing a middle name costs less than inventing an author."""
    names = [entry["name"] for entry in uploads._authors_from_metadata("J A Blumenthal, Babyak")]
    assert names == ["J A Blumenthal"]


# -- resolving a corpus for a run -------------------------------------------


async def test_a_corpus_of_one_is_refused():
    with pytest.raises(BadRequest) as caught:
        await uploads.resolve_for_run(["p1"], _StubDb())
    assert "at least" in caught.value.message


async def test_a_retrieved_paper_cannot_be_passed_off_as_an_upload():
    """Otherwise any paper id would build a corpus the reader never chose."""
    rows = [
        Paper(id="p1", semantic_scholar_id=uploads.fingerprint(b"a"), title="Mine"),
        Paper(id="p2", semantic_scholar_id="realsemanticscholarid", title="Theirs"),
    ]

    class _Rows:
        async def execute(self, *args, **kwargs):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    with pytest.raises(BadRequest) as caught:
        await uploads.resolve_for_run(["p1", "p2"], _Rows())
    assert caught.value.detail["papers"] == ["Theirs"]


async def test_papers_come_back_in_the_order_they_were_given():
    """The reader's order is the only ranking an upload run has."""
    rows = [
        Paper(id="p1", semantic_scholar_id=uploads.fingerprint(b"a"), title="First"),
        Paper(id="p2", semantic_scholar_id=uploads.fingerprint(b"b"), title="Second"),
    ]

    class _Rows:
        async def execute(self, *args, **kwargs):
            # Deliberately the other way round: the database has no order to
            # honour, so the caller's list has to be what decides.
            backwards = list(reversed(rows))
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: backwards))

    resolved = await uploads.resolve_for_run(["p1", "p2"], _Rows())
    assert [paper.title for paper in resolved] == ["First", "Second"]
