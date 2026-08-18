"""Shared API dependencies: database session, auth, pagination."""

from typing import Annotated

from fastapi import Depends, HTTPException, Query, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session

DBSession = Annotated[AsyncSession, Depends(get_session)]

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """Enforce X-API-Key when API_KEY is configured; open API when it is not.

    Auth is opt-in so local development stays frictionless, while any deployed
    instance can be locked down with a single environment variable.
    """
    if not settings.api_key:
        return
    if key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )


class Pagination:
    def __init__(
        self,
        limit: int = Query(50, ge=1, le=200, description="Maximum items to return"),
        offset: int = Query(0, ge=0, description="Items to skip"),
    ) -> None:
        self.limit = limit
        self.offset = offset


PageParams = Annotated[Pagination, Depends(Pagination)]
