"""API surface tests that do not require a live database.

Auth is checked before any DB access, so it is testable here; the data-path
endpoints are exercised by the end-to-end run (scripts/run_query.py) and the
eval harness.
"""

from typing import get_args
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def _allowed(field: str) -> tuple[str, ...]:
    """The Literal values a Settings provider field accepts."""
    return get_args(type(settings).model_fields[field].annotation)


@pytest.mark.asyncio
async def test_health_config_reports_active_providers(client: AsyncClient) -> None:
    response = await client.get("/health/config")
    assert response.status_code == 200

    data = response.json()
    # Derived from the settings schema rather than restated, so adding a provider
    # cannot leave this test asserting against a stale list.
    assert data["llm_provider"] in _allowed("llm_provider")
    assert data["embedding_provider"] in _allowed("embedding_provider")
    assert data["embedding_dim"] == 768
    # Secrets must never appear in a health payload.
    body = response.text.lower()
    assert "secret" not in body and "api_key" not in body


@pytest.mark.asyncio
async def test_routes_are_open_when_no_api_key_configured(client: AsyncClient) -> None:
    with patch.object(settings, "api_key", ""):
        response = await client.get("/api/v1/queries/")
    # Reaches the handler (DB may be unavailable in CI) rather than 401.
    assert response.status_code != 401


@pytest.mark.asyncio
async def test_missing_api_key_is_rejected(client: AsyncClient) -> None:
    with patch.object(settings, "api_key", "secret-key"):
        response = await client.get("/api/v1/queries/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_api_key_is_rejected(client: AsyncClient) -> None:
    with patch.object(settings, "api_key", "secret-key"):
        response = await client.get("/api/v1/queries/", headers={"X-API-Key": "nope"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_stays_public_when_auth_is_on(client: AsyncClient) -> None:
    with patch.object(settings, "api_key", "secret-key"):
        assert (await client.get("/health")).status_code == 200


def test_openapi_documents_the_full_surface() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    assert "/api/v1/queries/" in paths
    assert "/api/v1/queries/{query_id}/report" in paths
    assert "/api/v1/queries/{query_id}/report/export" in paths
    assert "/api/v1/queries/{query_id}/followup" in paths
    assert "/api/v1/claims/clusters/{cluster_id}" in paths
    # Phase 9 editing endpoints.
    assert "patch" in paths["/api/v1/claims/clusters/{cluster_id}"]
    assert "patch" in paths["/api/v1/queries/{query_id}/report"]


def test_websocket_route_is_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/queries/{query_id}/stream" in paths
