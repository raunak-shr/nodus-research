from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import retriever
from app.services.retriever import (
    build_bulk_variants,
    build_query,
    build_relevance_variants,
    build_year_filter,
    fetch_papers,
    sanitize,
)

# Captured before the autouse fixture patches it out, so the throttle itself
# can still be tested.
_REAL_THROTTLE = retriever._throttle


@pytest.fixture
def anonymous():
    """No API key — the tier where relevance search is refused outright."""
    with patch.object(retriever.settings, "semantic_scholar_api_key", ""):
        yield


@pytest.fixture(autouse=True)
def _no_throttle():
    """Retrieval throttling is real-time; tests should not pay for it."""
    with patch("app.services.retriever._throttle", new_callable=AsyncMock):
        retriever._last_request_at = 0.0
        retriever._relevance_available = None
        yield
        retriever._relevance_available = None


def _response(status_code: int, payload: dict | None = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = payload or {}
    resp.raise_for_status = MagicMock()
    return resp


def _client(responses: list):
    client = AsyncMock()
    client.get = AsyncMock(side_effect=responses)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return client, cm


# ------------------------------------------------------------- query building


def test_sanitize_strips_bulk_operators():
    assert sanitize("Does exercise reduce depression?") == "Does exercise reduce depression"
    assert sanitize('a + b | c "d"') == "a b c d"


def test_build_query_quotes_multiword_phrases():
    assert build_query(["aerobic exercise", "depression"]) == '"aerobic exercise" + depression'


def test_relevance_variants_are_plain_text():
    variants = build_relevance_variants(
        ["aerobic exercise", "depression", "RCT"], topic="exercise and depression"
    )
    assert variants[0] == "exercise and depression"
    assert all("+" not in v and "|" not in v for v in variants)


def test_bulk_variants_narrow_then_widen():
    variants = build_bulk_variants(["a", "b", "c", "d", "e"], topic="topic")
    assert variants[0] == "a + b"
    # The broadest variant ORs keywords for maximum recall.
    assert any("|" in v for v in variants)


def test_bulk_variants_lead_with_core_concepts():
    """Synonym keywords ANDed together match nothing; distinct concepts do."""
    variants = build_bulk_variants(
        ["aerobic exercise", "aerobic training", "aerobic physical activity"],
        topic="effect of aerobic exercise on depression",
        concepts=["aerobic exercise", "depression", "adults"],
    )
    assert variants[0] == '"aerobic exercise" + depression + adults'
    assert variants[1] == '"aerobic exercise" + depression'


def test_relevance_variants_lead_with_core_concepts():
    variants = build_relevance_variants(
        ["aerobic exercise", "aerobic training"],
        topic="effect of aerobic exercise on depression",
        concepts=["aerobic exercise", "depression", "adults"],
    )
    assert variants[0] == "aerobic exercise depression adults"


def test_bulk_variants_deduplicated():
    variants = build_bulk_variants(["a"], topic="a")
    assert len(variants) == len(set(variants))


def test_year_filter():
    assert build_year_filter(2015, 2024) == "2015-2024"
    assert build_year_filter(2015, None) == "2015-"
    assert build_year_filter(None, 2024) == "-2024"
    assert build_year_filter(None, None) is None


# ------------------------------------------------------------------ retrieval


@pytest.mark.asyncio
async def test_fetch_papers_returns_data_from_relevance_search():
    payload = {
        "data": [
            {"paperId": "abc123", "title": "Exercise and Depression", "citationCount": 42},
            {"paperId": "def456", "title": "RCT on Aerobic Training", "citationCount": 10},
        ]
    }
    client, cm = _client([_response(200, payload)])

    with patch("app.services.retriever.httpx.AsyncClient", return_value=cm):
        papers = await fetch_papers(["exercise", "depression"])

    assert [p["paperId"] for p in papers] == ["abc123", "def456"]
    url = client.get.call_args.args[0]
    assert url.endswith("/paper/search")
    # Relevance search supports tldr; bulk does not.
    assert "tldr" in client.get.call_args.kwargs["params"]["fields"]


@pytest.mark.asyncio
async def test_fetch_papers_widens_query_when_empty():
    client, cm = _client(
        [_response(200, {"data": []}), _response(200, {"data": [{"paperId": "x"}]})]
    )

    with patch("app.services.retriever.httpx.AsyncClient", return_value=cm):
        papers = await fetch_papers(["a", "b", "c"], topic="some topic")

    assert papers[0]["paperId"] == "x"
    assert client.get.await_count == 2


@pytest.mark.asyncio
async def test_fetch_papers_retries_on_429_then_succeeds():
    """With a key, a 429 is transient and worth backing off for."""
    client, cm = _client([_response(429), _response(200, {"data": [{"paperId": "xyz"}]})])

    with (
        patch("app.services.retriever.httpx.AsyncClient", return_value=cm),
        patch("app.services.retriever.asyncio.sleep", new_callable=AsyncMock) as sleep,
        patch("app.services.retriever.settings") as mock_settings,
    ):
        mock_settings.semantic_scholar_api_key = "key"
        mock_settings.retrieval_mode = "auto"
        papers = await fetch_papers(["test"])

    sleep.assert_awaited_once_with(1)  # 2**0 seconds on the first retry
    assert papers[0]["paperId"] == "xyz"


@pytest.mark.asyncio
async def test_relevance_rate_limit_falls_back_to_bulk(anonymous):
    """Anonymous relevance search 429s every time; bulk search still serves."""
    # One relevance probe (no key ⇒ no retries), then bulk answers.
    responses = [_response(429), _response(200, {"data": [{"paperId": "bulk1"}]})]
    client, cm = _client(responses)

    with (
        patch("app.services.retriever.httpx.AsyncClient", return_value=cm),
        patch("app.services.retriever.asyncio.sleep", new_callable=AsyncMock),
    ):
        papers = await fetch_papers(["exercise", "depression"], topic="exercise")

    assert papers[0]["paperId"] == "bulk1"
    assert client.get.call_args.args[0].endswith("/paper/search/bulk")
    assert client.get.call_args.kwargs["params"]["sort"] == "citationCount:desc"
    assert "tldr" not in client.get.call_args.kwargs["params"]["fields"]


@pytest.mark.asyncio
async def test_relevance_latch_skips_relevance_on_later_calls(anonymous):
    """Once relevance is known blocked, later queries go straight to bulk."""
    responses = [
        _response(429),  # relevance probe
        _response(200, {"data": [{"paperId": "bulk1"}]}),  # bulk
        _response(200, {"data": [{"paperId": "bulk2"}]}),  # second query: bulk directly
    ]
    client, cm = _client(responses)

    with (
        patch("app.services.retriever.httpx.AsyncClient", return_value=cm),
        patch("app.services.retriever.asyncio.sleep", new_callable=AsyncMock),
    ):
        await fetch_papers(["exercise"])
        papers = await fetch_papers(["nutrition"])

    assert papers[0]["paperId"] == "bulk2"
    assert client.get.await_count == 3
    assert all(
        call.args[0].endswith("/paper/search/bulk") for call in client.get.await_args_list[1:]
    )


@pytest.mark.asyncio
async def test_relevance_only_mode_does_not_fall_back():
    client, cm = _client([_response(429)] * 4)

    with (
        patch("app.services.retriever.httpx.AsyncClient", return_value=cm),
        patch("app.services.retriever.asyncio.sleep", new_callable=AsyncMock),
        patch("app.services.retriever.settings") as mock_settings,
    ):
        mock_settings.retrieval_mode = "relevance"
        mock_settings.semantic_scholar_api_key = ""
        with pytest.raises(retriever.RateLimited):
            await fetch_papers(["test"])


@pytest.mark.asyncio
async def test_rejected_query_returns_empty_and_tries_next_variant():
    client, cm = _client(
        [
            _response(400, text='{"error":"Unrecognized or unsupported fields: [tldr]"}'),
            _response(200, {"data": [{"paperId": "ok"}]}),
        ]
    )

    with patch("app.services.retriever.httpx.AsyncClient", return_value=cm):
        papers = await fetch_papers(["a", "b", "c"], topic="topic")

    assert papers[0]["paperId"] == "ok"


@pytest.mark.asyncio
async def test_fetch_papers_empty_when_nothing_matches():
    client, cm = _client([_response(200, {"data": []})] * 10)

    with patch("app.services.retriever.httpx.AsyncClient", return_value=cm):
        papers = await fetch_papers(["extremely niche query xyz"])

    assert papers == []


def test_min_interval_is_the_same_with_or_without_a_key():
    """An issued key grants a dedicated quota, not a higher ceiling (1 req/s)."""
    with patch.object(retriever.settings, "semantic_scholar_min_interval", 1.1):
        with patch.object(retriever.settings, "semantic_scholar_api_key", ""):
            anonymous = retriever._min_interval()
        with patch.object(retriever.settings, "semantic_scholar_api_key", "s2k-xyz"):
            keyed = retriever._min_interval()

    assert anonymous == keyed == 1.1
    assert keyed >= 1.0  # below 1s the API rejects requests


@pytest.mark.asyncio
async def test_throttle_spaces_out_consecutive_calls():
    sleeps: list[float] = []

    async def _record(seconds: float) -> None:
        sleeps.append(seconds)

    with (
        patch.object(retriever.settings, "semantic_scholar_min_interval", 1.1),
        patch("app.services.retriever.asyncio.sleep", new=_record),
    ):
        retriever._last_request_at = 0.0
        retriever._throttle_lock = None
        await _REAL_THROTTLE()  # first call: no wait
        await _REAL_THROTTLE()  # second: must wait out the interval

    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 1.1


@pytest.mark.asyncio
async def test_fetch_papers_attaches_api_key_header():
    client, cm = _client([_response(200, {"data": []})] * 10)

    with (
        patch("app.services.retriever.httpx.AsyncClient", return_value=cm),
        patch("app.services.retriever.settings") as mock_settings,
    ):
        mock_settings.semantic_scholar_api_key = "test-key-123"
        mock_settings.retrieval_mode = "auto"
        await fetch_papers(["test"])

    assert client.get.call_args.kwargs["headers"]["x-api-key"] == "test-key-123"


@pytest.mark.asyncio
async def test_fetch_papers_applies_year_filter():
    client, cm = _client([_response(200, {"data": [{"paperId": "a"}]})])

    with patch("app.services.retriever.httpx.AsyncClient", return_value=cm):
        await fetch_papers(["test"], year_start=2015, year_end=2024)

    assert client.get.call_args.kwargs["params"]["year"] == "2015-2024"


@pytest.mark.asyncio
async def test_fetch_tldrs_maps_ids_to_payloads():
    resp = _response(200)
    resp.json.return_value = [
        {"paperId": "a", "tldr": {"text": "short summary"}},
        {"paperId": "b", "tldr": None},
    ]
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.retriever.httpx.AsyncClient", return_value=cm):
        tldrs = await retriever.fetch_tldrs(["a", "b"])

    assert tldrs == {"a": {"text": "short summary"}}


@pytest.mark.asyncio
async def test_fetch_tldrs_swallows_failures():
    with patch("app.services.retriever.httpx.AsyncClient", side_effect=RuntimeError("boom")):
        assert await retriever.fetch_tldrs(["a"]) == {}
