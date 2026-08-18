"""Entra ID (Azure AD) client-credentials token provider.

The Azure OpenAI deployment sits behind APIM and authenticates with a bearer
token rather than an API key, so every request needs a freshly minted (and
cached) access token. Tokens are cached in-process until 5 minutes before
expiry and refreshed under a lock so concurrent agents mint at most one token.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import httpx

from app.core.config import settings
from app.core.tls import outbound_verify

logger = logging.getLogger(__name__)

_REFRESH_MARGIN_SECONDS = 300.0

_token: str | None = None
_expires_at: float = 0.0
_async_lock: asyncio.Lock | None = None
_sync_lock = threading.Lock()


def _token_url() -> str:
    return f"https://login.microsoftonline.com/{settings.llm_azure_tenant_id}/oauth2/v2.0/token"


def _form() -> dict[str, str]:
    return {
        "grant_type": "client_credentials",
        "client_id": settings.llm_azure_client_id,
        "client_secret": settings.llm_azure_client_secret,
        "scope": settings.llm_azure_scope,
    }


def _store(payload: dict) -> str:
    global _token, _expires_at
    _token = payload["access_token"]
    _expires_at = time.monotonic() + float(payload.get("expires_in", 3600))
    return _token


def _cached() -> str | None:
    if _token and time.monotonic() < _expires_at - _REFRESH_MARGIN_SECONDS:
        return _token
    return None


def _require_config() -> None:
    if not settings.azure_configured:
        raise RuntimeError(
            "Azure OpenAI is not configured. Set LLM_AZURE_ENDPOINT, "
            "LLM_AZURE_TENANT_ID, LLM_AZURE_CLIENT_ID and LLM_AZURE_CLIENT_SECRET."
        )


def get_token() -> str:
    """Return a valid access token, minting one synchronously if needed."""
    cached = _cached()
    if cached:
        return cached

    _require_config()
    with _sync_lock:
        cached = _cached()
        if cached:
            return cached
        with httpx.Client(timeout=30.0, verify=outbound_verify()) as client:
            resp = client.post(_token_url(), data=_form())
            resp.raise_for_status()
            logger.debug("Minted Entra ID token (sync)")
            return _store(resp.json())


async def get_token_async() -> str:
    """Return a valid access token without blocking the event loop."""
    global _async_lock

    cached = _cached()
    if cached:
        return cached

    _require_config()
    if _async_lock is None:
        _async_lock = asyncio.Lock()
    async with _async_lock:
        cached = _cached()
        if cached:
            return cached
        async with httpx.AsyncClient(timeout=30.0, verify=outbound_verify()) as client:
            resp = await client.post(_token_url(), data=_form())
            resp.raise_for_status()
            logger.debug("Minted Entra ID token (async)")
            return _store(resp.json())


def reset_cache() -> None:
    """Drop the cached token — used by tests and the connectivity check."""
    global _token, _expires_at
    _token = None
    _expires_at = 0.0
