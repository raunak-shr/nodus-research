"""Shared API dependencies: database session, auth, rate limiting, pagination."""

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.services import limits, ownership

DBSession = Annotated[AsyncSession, Depends(get_session)]

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def _matches(provided: str | None, expected: str) -> bool:
    """Constant-time comparison — a key check should not leak its prefix."""
    return secrets.compare_digest(provided or "", expected)


async def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """Enforce X-API-Key when API_KEY is configured; open API when it is not.

    Auth is opt-in so local development stays frictionless, while any deployed
    instance can be locked down with a single environment variable.
    """
    if not settings.api_key:
        return
    if not _matches(key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )


async def is_admin(key: str | None = Security(_admin_key_header)) -> bool:
    """Whether the caller holds the admin key.

    An unset ADMIN_API_KEY makes nobody an admin, so admin-only paths stay shut
    on a public deployment rather than opening by default.
    """
    if not settings.admin_api_key:
        return False
    return _matches(key, settings.admin_api_key)


AdminCaller = Annotated[bool, Depends(is_admin)]


async def resolve_owner(
    request: Request,
    x_nodus_owner: Annotated[
        str | None, Header(description="Owner token: which history this request reads")
    ] = None,
) -> str:
    """Whose history this request reads.

    Not a credential — it is the identity the caller supplied, and it decides
    which queries exist as far as this request is concerned. A caller that sends
    nothing gets one derived from its address, so `curl` and the scripts can
    still read back the runs they started. See `app/services/ownership.py`.
    """
    return ownership.resolve_owner(
        x_nodus_owner,
        client_host=request.client.host if request.client else None,
        forwarded_for=request.headers.get("x-forwarded-for"),
    )


Owner = Annotated[str, Depends(resolve_owner)]


def _client_key(request: Request) -> str:
    return limits.client_key(
        client_host=request.client.host if request.client else None,
        forwarded_for=request.headers.get("x-forwarded-for"),
    )


async def rate_limit_runs(request: Request) -> None:
    """Throttle the LLM-heavy writes: new runs, follow-ups, regeneration."""
    limits.runs_limiter.check(_client_key(request))


async def rate_limit_edits(request: Request) -> None:
    """Throttle cluster and report edits — cheap per call, unbounded in a loop."""
    limits.edits_limiter.check(_client_key(request))


async def rate_limit_interprets(request: Request) -> None:
    """Throttle the Interpret check: LLM calls without a run to pay for them."""
    limits.interprets_limiter.check(_client_key(request))


# Applied per route rather than per router: reads stay unthrottled, and these run
# after the router-level auth dependency, so a rejected caller never spends a
# legitimate caller's budget.
RunRateLimit = Depends(rate_limit_runs)
EditRateLimit = Depends(rate_limit_edits)
InterpretRateLimit = Depends(rate_limit_interprets)


class Pagination:
    def __init__(
        self,
        limit: int = Query(50, ge=1, le=200, description="Maximum items to return"),
        offset: int = Query(0, ge=0, description="Items to skip"),
    ) -> None:
        self.limit = limit
        self.offset = offset


PageParams = Annotated[Pagination, Depends(Pagination)]
