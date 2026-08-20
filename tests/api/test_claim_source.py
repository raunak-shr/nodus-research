"""The claim-source read model and the two surfaces that expose it.

`load_claim_source` is driven against a stub session rather than Postgres: what
matters here is the available/unavailable branching and whether the highlight
offsets it sends actually land on the quote.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v2.actions import REGISTRY
from app.main import app
from app.services import provenance
from app.services.errors import NotFound

BODY = (
    "Results\n"
    "Aerobic exercise reduced depression severity by 4.2 points on the BDI-II "
    "(95% CI [2.1, 6.3], p = 0.003).\n\n"
    "Discussion\n"
    "The effect was smaller in older participants.\n"
)
QUOTE = "Aerobic exercise reduced depression severity by 4.2 points"


class _StubResult:
    def __init__(self, row) -> None:
        self._row = row

    def first(self):
        return self._row


class _StubDb:
    """Returns one prepared row for the single query the loader makes."""

    def __init__(self, row) -> None:
        self._row = row

    async def execute(self, *args, **kwargs):
        return _StubResult(self._row)


def _paper():
    return SimpleNamespace(
        id=uuid4(),
        title="Exercise and depression",
        abstract="Exercise reduced depression severity.",
        open_access_pdf_url="https://example.org/paper.pdf",
        publication_year=2021,
        authors=[{"name": "Ada Lovelace"}],
    )


def _claim(**overrides):
    start = BODY.index(QUOTE)
    defaults = {
        "id": uuid4(),
        "claim_text": "Aerobic exercise reduces depression severity.",
        "source_quote": QUOTE,
        "source_section": "results",
        "source_start": start,
        "source_end": start + len(QUOTE),
        "source_page": 2,
        "source_match": "exact",
        "source_origin": "full_text",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def test_located_claim_returns_a_highlightable_paragraph():
    paper = _paper()
    claim = _claim()
    normalized = SimpleNamespace(full_text=BODY, page_offsets=[0, 40], sections=None)

    source = await provenance.load_claim_source(claim.id, _StubDb((claim, paper, normalized)))

    assert source.available is True
    assert source.match == "exact"
    assert source.origin == "full_text"
    assert source.section == "results"
    assert source.page == 2
    assert source.pdf_url == "https://example.org/paper.pdf"
    assert source.citation == "Lovelace, 2021"
    # The offsets the client is given must highlight the quote inside `context`.
    assert source.context[source.highlight_start : source.highlight_end] == QUOTE


async def test_unlocated_claim_is_unavailable_but_keeps_the_quote():
    """A reader can still search the PDF by hand for what the model said it read."""
    paper = _paper()
    claim = _claim(source_match="none", source_start=None, source_end=None, source_page=None)
    normalized = SimpleNamespace(full_text=BODY, page_offsets=None, sections=None)

    source = await provenance.load_claim_source(claim.id, _StubDb((claim, paper, normalized)))

    assert source.available is False
    assert source.match == "none"
    assert source.quote == QUOTE
    assert source.context is None
    assert source.highlight_start is None


async def test_claim_from_a_paper_with_no_source_text_is_unavailable():
    paper = _paper()
    paper.abstract = None
    claim = _claim()

    source = await provenance.load_claim_source(claim.id, _StubDb((claim, paper, None)))

    assert source.available is False
    assert source.context is None


async def test_abstract_only_claim_reports_its_origin():
    paper = _paper()
    quote = "Exercise reduced depression severity."
    claim = _claim(
        source_quote=quote,
        source_start=paper.abstract.index(quote),
        source_end=paper.abstract.index(quote) + len(quote),
        source_page=None,
        source_section=None,
        source_origin="abstract",
    )

    source = await provenance.load_claim_source(claim.id, _StubDb((claim, paper, None)))

    assert source.available is True
    assert source.origin == "abstract"
    assert source.page is None
    assert source.context[source.highlight_start : source.highlight_end] == quote


async def test_missing_claim_raises_not_found():
    with pytest.raises(NotFound):
        await provenance.load_claim_source(uuid4(), _StubDb(None))


# ------------------------------------------------------------------ surfaces


def test_rest_route_is_registered():
    paths = app.openapi()["paths"]
    assert "/api/v1/claims/{claim_id}/source" in paths
    assert "get" in paths["/api/v1/claims/{claim_id}/source"]


def test_rest_route_does_not_shadow_the_cluster_routes():
    """`/claims/{claim_id}/source` and `/claims/clusters/{id}` are both two deep."""
    paths = app.openapi()["paths"]
    assert "/api/v1/claims/clusters/{cluster_id}" in paths
    assert "/api/v1/claims/clusters/queries/{query_id}" in paths


def test_socket_action_is_registered_as_a_read():
    action = REGISTRY["claims.source"]
    assert action.cost == "read"
    assert list(action.params.model_fields) == ["claim_id"]


def test_describe_publishes_the_new_action():
    with TestClient(app) as client, client.websocket_connect("/api/v2/ws") as socket:
        ready = socket.receive_json()
        assert "claims.source" in ready["actions"]

        socket.send_json({"id": "1", "action": "meta.describe"})
        described = {
            item["name"]: item["cost"] for item in socket.receive_json()["data"]["actions"]
        }
    assert described["claims.source"] == "read"


# --------------------------------------------------------- origin and reason


async def test_origin_is_read_from_the_claim_not_re_derived():
    """A claim resolved against the abstract stays abstract-only.

    The UI branches on origin before match, so re-deriving it from whatever text
    happens to be on the paper now would relabel an abstract-only quote as
    verified against the body.
    """
    paper = _paper()
    quote = "Exercise reduced depression severity."
    claim = _claim(
        source_quote=quote,
        source_start=paper.abstract.index(quote),
        source_end=paper.abstract.index(quote) + len(quote),
        source_match="normalized",
        source_origin="abstract",
        source_page=None,
    )
    # Full text exists now, but this claim was not resolved against it.
    normalized = SimpleNamespace(full_text=BODY, page_offsets=[0], sections=None)

    source = await provenance.load_claim_source(claim.id, _StubDb((claim, paper, normalized)))

    assert source.origin == "abstract"
    assert "abstract" in source.reason.lower()


async def test_a_verified_body_quote_needs_no_caveat():
    paper = _paper()
    normalized = SimpleNamespace(full_text=BODY, page_offsets=[0], sections=None)

    source = await provenance.load_claim_source(
        claim_id := _claim().id, _StubDb((_claim(id=claim_id), paper, normalized))
    )

    assert source.match == "exact"
    assert source.reason is None


async def test_a_fuzzy_span_says_it_is_approximate():
    paper = _paper()
    claim = _claim(source_match="fuzzy")
    normalized = SimpleNamespace(full_text=BODY, page_offsets=[0], sections=None)

    source = await provenance.load_claim_source(claim.id, _StubDb((claim, paper, normalized)))

    assert source.available is True
    assert "approximate" in source.reason.lower()


async def test_an_unlocated_body_quote_blames_truncation_not_the_reader():
    paper = _paper()
    claim = _claim(source_match="none", source_start=None, source_end=None)
    normalized = SimpleNamespace(full_text=BODY, page_offsets=[0], sections=None)

    source = await provenance.load_claim_source(claim.id, _StubDb((claim, paper, normalized)))

    assert source.available is False
    assert "truncated" in source.reason.lower()


async def test_no_source_text_at_all_explains_itself():
    paper = _paper()
    paper.abstract = None
    claim = _claim()

    source = await provenance.load_claim_source(claim.id, _StubDb((claim, paper, None)))

    assert source.available is False
    assert source.reason is not None
    assert "nothing to locate" in source.reason.lower()


def test_explain_covers_every_state():
    """Every state a chip can render must have words to go with it."""
    assert (
        provenance.explain(match="exact", origin="full_text", has_source=True, located=True) is None
    )
    for kwargs in (
        {"match": "exact", "origin": None, "has_source": False, "located": False},
        {"match": "normalized", "origin": "abstract", "has_source": True, "located": True},
        {"match": "none", "origin": "abstract", "has_source": True, "located": False},
        {"match": "none", "origin": "full_text", "has_source": True, "located": False},
        {"match": "fuzzy", "origin": "full_text", "has_source": True, "located": True},
        {"match": "normalized", "origin": "full_text", "has_source": True, "located": True},
    ):
        assert provenance.explain(**kwargs)


async def test_context_comes_from_the_text_the_offsets_were_resolved_against():
    """A late-arriving PDF must not repoint an abstract-only claim.

    The claim below indexes the abstract. Full text exists now, and slicing it at
    those offsets would show an unrelated passage as though it were the source.
    """
    paper = _paper()
    quote = "Exercise reduced depression severity."
    start = paper.abstract.index(quote)
    claim = _claim(
        source_quote=quote,
        source_start=start,
        source_end=start + len(quote),
        source_origin="abstract",
        source_page=None,
        source_section=None,
    )
    normalized = SimpleNamespace(full_text=BODY, page_offsets=[0], sections=None)

    source = await provenance.load_claim_source(claim.id, _StubDb((claim, paper, normalized)))

    assert source.origin == "abstract"
    assert source.context[source.highlight_start : source.highlight_end] == quote
    # Not a slice of the body, which is what the old code would have returned.
    assert "BDI-II" not in (source.context or "")


async def test_a_claim_whose_recorded_text_is_gone_is_unavailable():
    """Offsets into a full text that no longer exists must not fall back."""
    paper = _paper()
    claim = _claim(source_origin="full_text")
    normalized = SimpleNamespace(full_text=None, page_offsets=None, sections=None)

    source = await provenance.load_claim_source(claim.id, _StubDb((claim, paper, normalized)))

    assert source.available is False
    assert source.context is None
