"""arXiv fallback: identifier handling, match verification, and the throttle.

Hermetic — every arxiv.org call is served by an httpx MockTransport, and the
throttle interval is driven to zero so the suite does not spend three seconds
per simulated request proving that it would have.
"""

from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from app.services import arxiv, pdf

#: Captured before any test patches the name the modules under test read.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

MINIMAL_PDF = b"%PDF-1.4 pretend this parses"


def _feed(*entries: str, total: int | None = None) -> str:
    count = len(entries) if total is None else total
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
        f"<opensearch:totalResults>{count}</opensearch:totalResults>"
        + "".join(entries)
        + "</feed>"
    )


def _entry(arxiv_id: str, title: str, authors: list[str]) -> str:
    people = "".join(f"<author><name>{name}</name></author>" for name in authors)
    return (
        "<entry>"
        f"<id>http://arxiv.org/abs/{arxiv_id}</id>"
        f"<title>{title}</title>"
        f"{people}"
        "</entry>"
    )


TARGET_TITLE = "Attention Is All You Need"
TARGET_AUTHORS = [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}]


def _transport(routes, seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        for prefix, (body, content_type) in routes.items():
            if str(request.url).startswith(prefix):
                if isinstance(body, str):
                    body = body.encode()
                return httpx.Response(200, content=body, headers={"content-type": content_type})
        return httpx.Response(404, request=request)

    return httpx.MockTransport(handler)


def _client_factory(routes, seen):
    def build(**kwargs):
        kwargs.pop("verify", None)  # a MockTransport has nothing to verify
        return _REAL_ASYNC_CLIENT(transport=_transport(routes, seen), **kwargs)

    return build


@contextmanager
def _serving(routes, seen, *, min_interval=0.0):
    factory = _client_factory(routes, seen)
    with (
        patch.object(arxiv.httpx, "AsyncClient", factory),
        patch.object(pdf.httpx, "AsyncClient", factory),
        patch.object(arxiv.settings, "arxiv_min_interval", min_interval),
        patch.object(
            pdf,
            "_extract_document",
            lambda data, source=None: pdf.PdfDocument(
                text="body text", page_offsets=[0], source=source
            ),
        ),
    ):
        yield


# --- identifiers -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2301.12345", "2301.12345"),
        ("arXiv:2301.12345", "2301.12345"),
        ("http://arxiv.org/abs/1706.03762v5", "1706.03762v5"),
        ("https://arxiv.org/pdf/2301.12345", "2301.12345"),
        ("math.GT/0309136", "math.GT/0309136"),
        ("hep-th/9901001", "hep-th/9901001"),
        ("", None),
        (None, None),
        ("not an identifier", None),
    ],
)
def test_normalize_id_accepts_every_form_the_id_arrives_in(raw, expected):
    assert arxiv.normalize_id(raw) == expected


def test_the_version_suffix_is_kept():
    """`v5` names a specific revision. arXiv serves the latest when none is
    given, so dropping it would silently change which document was read."""
    assert arxiv.normalize_id("1706.03762v5") == "1706.03762v5"
    assert arxiv.pdf_url("1706.03762v5") == "https://arxiv.org/pdf/1706.03762v5"


# --- verification ----------------------------------------------------------


def test_a_matching_title_and_one_shared_author_is_a_match():
    record = arxiv.ArxivRecord(
        arxiv_id="1706.03762",
        title="Attention is all you need",
        authors=["Ashish Vaswani", "Llion Jones"],
    )
    assert arxiv.matches(record, TARGET_TITLE, TARGET_AUTHORS)


def test_a_different_paper_on_the_same_subject_is_rejected():
    record = arxiv.ArxivRecord(
        arxiv_id="9999.00001",
        title="Attention is not all you need: pure attention loses rank",
        authors=["Ashish Vaswani"],
    )
    assert not arxiv.matches(record, TARGET_TITLE, TARGET_AUTHORS)


def test_no_shared_author_vetoes_a_title_that_would_otherwise_pass():
    """Two groups can publish near-identical titles; the text of one must never
    become the evidence attributed to the other."""
    record = arxiv.ArxivRecord(
        arxiv_id="9999.00002",
        title="Attention Is All You Need",
        authors=["Someone Else", "Another Person"],
    )
    assert not arxiv.matches(record, TARGET_TITLE, TARGET_AUTHORS)


def test_authors_cannot_veto_when_one_side_lists_none():
    """Bulk search omits authors for some papers. An empty list is no evidence
    of a mismatch, so the title has to carry the decision alone."""
    record = arxiv.ArxivRecord(
        arxiv_id="1706.03762", title="Attention Is All You Need", authors=[]
    )
    assert arxiv.matches(record, TARGET_TITLE, TARGET_AUTHORS)
    assert arxiv.matches(record, TARGET_TITLE, [])


def test_punctuation_and_case_do_not_decide_a_match():
    record = arxiv.ArxivRecord(
        arxiv_id="1706.03762",
        title="ATTENTION IS ALL YOU NEED.",
        authors=["A. Vaswani"],
    )
    assert arxiv.matches(record, TARGET_TITLE, TARGET_AUTHORS)


# --- feed parsing ----------------------------------------------------------


def test_parse_feed_reads_id_title_and_authors():
    xml = _feed(_entry("1706.03762v5", "Attention Is All\n  You Need", ["Ashish Vaswani"]))

    records = arxiv.parse_feed(xml)

    assert len(records) == 1
    assert records[0].arxiv_id == "1706.03762v5"
    # arXiv wraps long titles across lines; the whitespace is not part of them.
    assert records[0].title == "Attention Is All You Need"
    assert records[0].authors == ["Ashish Vaswani"]


def test_parse_feed_handles_an_empty_result_set():
    assert arxiv.parse_feed(_feed(total=0)) == []


def test_parse_feed_swallows_malformed_xml():
    """An arXiv outage that returns an HTML error page must cost this paper its
    full text and nothing more."""
    assert arxiv.parse_feed("<html>service unavailable") == []


# --- queries ---------------------------------------------------------------


def test_the_first_query_pins_the_title_field_and_an_author():
    queries = arxiv.build_search_queries(TARGET_TITLE, TARGET_AUTHORS)

    assert queries[0] == 'ti:"attention is all you need" AND au:"shazeer"'
    # All-fields second: a preprint whose title was revised before publication
    # keeps the phrase in its abstract even when `ti:` can no longer find it.
    assert queries[1] == 'all:"attention is all you need"'


def test_a_title_with_punctuation_does_not_reach_the_query_language():
    queries = arxiv.build_search_queries("Deep learning: a review (2020)!", [])

    assert queries[0] == 'ti:"deep learning a review 2020"'


def test_no_title_means_no_queries():
    assert arxiv.build_search_queries("", TARGET_AUTHORS) == []
    assert arxiv.build_search_queries("!!!", []) == []


# --- end to end ------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_identifier_goes_straight_to_the_pdf():
    """The whole point of storing `externalIds.ArXiv`: no search, no matching
    risk, one request."""
    seen: list[httpx.Request] = []
    routes = {"https://arxiv.org/pdf/1706.03762": (MINIMAL_PDF, "application/pdf")}

    with _serving(routes, seen):
        document = await arxiv.fetch_document(
            arxiv_id="arXiv:1706.03762", title=TARGET_TITLE, authors=TARGET_AUTHORS
        )

    assert document is not None
    assert document.source == "arxiv"
    assert [str(r.url) for r in seen] == ["https://arxiv.org/pdf/1706.03762"]


@pytest.mark.asyncio
async def test_without_an_identifier_the_paper_is_searched_for_by_title():
    seen: list[httpx.Request] = []
    routes = {
        "https://export.arxiv.org/api/query": (
            _feed(_entry("1706.03762", TARGET_TITLE, ["Ashish Vaswani"])),
            "application/atom+xml",
        ),
        "https://arxiv.org/pdf/1706.03762": (MINIMAL_PDF, "application/pdf"),
    }

    with _serving(routes, seen):
        document = await arxiv.fetch_document(title=TARGET_TITLE, authors=TARGET_AUTHORS)

    assert document is not None
    assert document.source == "arxiv"
    assert str(seen[0].url).startswith("https://export.arxiv.org/api/query")
    assert str(seen[-1].url) == "https://arxiv.org/pdf/1706.03762"


@pytest.mark.asyncio
async def test_an_unverifiable_hit_is_not_downloaded():
    """A wrong match costs more than no match: its text would be extracted as
    this paper's evidence."""
    seen: list[httpx.Request] = []
    routes = {
        "https://export.arxiv.org/api/query": (
            _feed(_entry("9999.00003", "Something else entirely", ["Nobody Here"])),
            "application/atom+xml",
        ),
    }

    with _serving(routes, seen):
        document = await arxiv.fetch_document(title=TARGET_TITLE, authors=TARGET_AUTHORS)

    assert document is None
    assert all("arxiv.org/pdf" not in str(r.url) for r in seen)


@pytest.mark.asyncio
async def test_the_search_gives_up_after_two_queries():
    """Each query costs three seconds of throttle; a title two phrase searches
    cannot find will not be found by a third."""
    seen: list[httpx.Request] = []
    routes = {"https://export.arxiv.org/api/query": (_feed(total=0), "application/atom+xml")}

    with _serving(routes, seen):
        assert await arxiv.fetch_document(title=TARGET_TITLE, authors=TARGET_AUTHORS) is None

    assert len(seen) == 2


@pytest.mark.asyncio
async def test_the_title_search_can_be_turned_off_on_its_own():
    """The identifier route is exact; the search is the only one that can match
    the wrong paper, so it is separately disableable."""
    seen: list[httpx.Request] = []

    with _serving({}, seen), patch.object(arxiv.settings, "arxiv_search_by_title", False):
        assert await arxiv.fetch_document(title=TARGET_TITLE, authors=TARGET_AUTHORS) is None

    assert seen == []


@pytest.mark.asyncio
async def test_the_whole_fallback_can_be_turned_off():
    seen: list[httpx.Request] = []

    with _serving({}, seen), patch.object(arxiv.settings, "arxiv_fallback", False):
        assert await arxiv.fetch_document(arxiv_id="1706.03762") is None

    assert seen == []


@pytest.mark.asyncio
async def test_a_failed_search_leaves_the_paper_to_its_abstract():
    seen: list[httpx.Request] = []
    routes = {"https://export.arxiv.org/api/query": ("500 error", "text/html")}

    with _serving(routes, seen):
        # 404 from the mock transport — every arXiv failure is the same answer.
        assert await arxiv.fetch_document(title="Nothing findable", authors=[]) is None


# --- throttle --------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_arxiv_call_waits_behind_the_previous_one():
    """arXiv asks for a three second delay. Papers process ten at a time, so
    without one shared throttle a run would burst twenty requests at once."""
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    seen: list[httpx.Request] = []
    routes = {
        "https://export.arxiv.org/api/query": (
            _feed(_entry("1706.03762", TARGET_TITLE, ["Ashish Vaswani"])),
            "application/atom+xml",
        ),
        "https://arxiv.org/pdf/1706.03762": (MINIMAL_PDF, "application/pdf"),
    }

    arxiv._last_request_at = 0.0
    with (
        _serving(routes, seen, min_interval=3.0),
        patch.object(arxiv.asyncio, "sleep", fake_sleep),
    ):
        await arxiv.fetch_document(title=TARGET_TITLE, authors=TARGET_AUTHORS)

    # The search and the download it leads to are both arxiv.org, and the
    # second of them had to wait: one throttle covers the pair.
    assert len(seen) == 2
    assert len(slept) >= 1
    assert max(slept) <= 3.0
