from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_fetch_papers_returns_data():
    mock_data = {
        "data": [
            {"paperId": "abc123", "title": "Exercise and Depression", "citationCount": 42},
            {"paperId": "def456", "title": "RCT on Aerobic Training", "citationCount": 10},
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_data
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.retriever.httpx.AsyncClient", return_value=mock_cm):
        from app.services.retriever import fetch_papers

        papers = await fetch_papers(["exercise", "depression"])

    assert len(papers) == 2
    assert papers[0]["paperId"] == "abc123"
    assert papers[1]["paperId"] == "def456"


@pytest.mark.asyncio
async def test_fetch_papers_empty_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.retriever.httpx.AsyncClient", return_value=mock_cm):
        from app.services.retriever import fetch_papers

        papers = await fetch_papers(["extremely niche query xyz"])

    assert papers == []


@pytest.mark.asyncio
async def test_fetch_papers_retries_on_429():

    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.raise_for_status = MagicMock(side_effect=Exception("429 Too Many Requests"))

    mock_ok = MagicMock()
    mock_ok.status_code = 200
    mock_ok.json.return_value = {"data": [{"paperId": "xyz"}]}
    mock_ok.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[mock_429, mock_ok])

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.retriever.httpx.AsyncClient", return_value=mock_cm),
        patch("app.services.retriever.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        from app.services.retriever import fetch_papers

        papers = await fetch_papers(["test"])

    mock_sleep.assert_called_once_with(1)  # 2^0 = 1 second on first retry
    assert papers[0]["paperId"] == "xyz"


@pytest.mark.asyncio
async def test_fetch_papers_attaches_api_key_header():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.retriever.httpx.AsyncClient", return_value=mock_cm),
        patch("app.services.retriever.settings") as mock_settings,
    ):
        mock_settings.semantic_scholar_api_key = "test-key-123"

        from app.services.retriever import fetch_papers

        await fetch_papers(["test"])

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("x-api-key") == "test-key-123"
