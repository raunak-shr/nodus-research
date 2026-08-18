"""Discover how a new Azure/APIM endpoint wants to be called.

APIM routes vary: some expose the deployment as a flat operation
(``POST <endpoint>``), some keep the ``/openai/deployments/<name>/`` prefix.
This probe tries the plausible shapes and reports what each answered, so
LLM_AZURE_ENDPOINT / LLM_AZURE_DEPLOYMENT / LLM_AZURE_FLAT_ROUTE can be set
from evidence rather than guesswork.

    uv run python scripts/probe_azure_route.py

Reading the results:
    200  this is the route
    401  route exists, credentials are incomplete (an APIM subscription key
         in LLM_API_KEY is usually what is missing)
    404  wrong path — try another shape
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from app.core.azure_auth import get_token_async
from app.core.config import settings
from app.core.tls import outbound_verify

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_CHAT_BODY = {
    "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
    "max_completion_tokens": 16,
}


async def main() -> int:
    base = settings.llm_azure_endpoint.rstrip("/")
    version = settings.llm_azure_api_version
    model = settings.llm_azure_model

    if not base:
        print("LLM_AZURE_ENDPOINT is not set", file=sys.stderr)
        return 2

    token = await get_token_async()
    print(f"endpoint : {base}")
    print(f"version  : {version}")
    print(f"token    : acquired ({len(token)} chars)")
    print(f"apim key : {'set' if settings.llm_api_key else 'NOT SET'}\n")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Ocp-Apim-Subscription-Key"] = settings.llm_api_key

    candidates = {
        "flat operation (LLM_AZURE_FLAT_ROUTE=true)": f"{base}?api-version={version}",
        "standard chat completions": f"{base}/chat/completions?api-version={version}",
        "deployment-prefixed": (
            f"{base}/openai/deployments/{model}/chat/completions?api-version={version}"
        ),
        "v1 passthrough": f"{base}/openai/v1/chat/completions?api-version={version}",
    }

    async with httpx.AsyncClient(timeout=90.0, verify=outbound_verify()) as client:
        for label, url in candidates.items():
            try:
                response = await client.post(url, headers=headers, json=_CHAT_BODY)
                print(
                    f"[{response.status_code}] {label}\n      {url}\n"
                    f"      {response.text[:220]}\n"
                )
            except Exception as exc:  # noqa: BLE001 - diagnostics only
                print(f"[EXC] {label}\n      {url}\n      {exc!r}\n")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
