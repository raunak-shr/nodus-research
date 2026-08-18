"""Outbound TLS configuration for HTTP clients.

Corporate proxies re-sign HTTPS with a root that lives in the OS trust store
but not in certifi's bundle. `truststore` bridges that gap — but it must stay
scoped to httpx clients: injecting it globally replaces `ssl.SSLContext`, and
asyncio's `start_tls` then rejects the database connection's context with
"sslcontext is expected to be an instance of ssl.SSLContext".
"""

from __future__ import annotations

import functools
import logging
import ssl

from app.core.config import settings

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def outbound_verify() -> ssl.SSLContext | bool:
    """Return a `verify` value for httpx: an OS-trust context, or True."""
    if not settings.use_system_ca:
        return True
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:  # pragma: no cover - optional dependency
        logger.debug("truststore not installed; using certifi trust store")
        return True
