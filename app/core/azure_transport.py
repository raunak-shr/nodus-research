"""httpx transports that adapt the OpenAI SDK to an APIM-fronted deployment.

The OpenAI SDK always appends an operation path (`/chat/completions`,
`/embeddings`, …) to its base URL. Our APIM route exposes the deployment as a
single flat operation — `POST https://…/openai5/az_openai_gpt-51_chat` — so the
appended suffix has to be stripped back off before the request goes out.
Everything else (auth headers, retries, streaming) is left untouched.
"""

from __future__ import annotations

import re

import httpx

from app.core.tls import outbound_verify

_OPERATION_SUFFIXES = (
    "/chat/completions",
    "/completions",
    "/embeddings",
    "/responses",
)

# The Azure SDK also injects /deployments/<model> ahead of the operation.
_DEPLOYMENT_SEGMENT = re.compile(r"/deployments/[^/]+$")


def _flatten(url: httpx.URL) -> httpx.URL | None:
    """Reduce an SDK-built Azure path back to the flat APIM operation path."""
    path = url.path
    changed = False

    for suffix in _OPERATION_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            changed = True
            break

    match = _DEPLOYMENT_SEGMENT.search(path)
    if match:
        path = path[: match.start()]
        changed = True

    if not changed:
        return None
    return url.copy_with(path=path or "/")


class FlatRouteAsyncTransport(httpx.AsyncBaseTransport):
    """Strips the SDK-appended operation suffix from outgoing async requests."""

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport(verify=outbound_verify())

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        flattened = _flatten(request.url)
        if flattened is not None:
            request.url = flattened
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


class FlatRouteTransport(httpx.BaseTransport):
    """Synchronous counterpart of :class:`FlatRouteAsyncTransport`."""

    def __init__(self, inner: httpx.BaseTransport | None = None) -> None:
        self._inner = inner or httpx.HTTPTransport(verify=outbound_verify())

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        flattened = _flatten(request.url)
        if flattened is not None:
            request.url = flattened
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def build_clients(timeout: float) -> tuple[httpx.Client, httpx.AsyncClient]:
    """Return (sync, async) httpx clients that flatten APIM operation paths."""
    return (
        httpx.Client(transport=FlatRouteTransport(), timeout=timeout),
        httpx.AsyncClient(transport=FlatRouteAsyncTransport(), timeout=timeout),
    )
