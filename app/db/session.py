"""Async engine and session factory.

Hosted Postgres (Supabase, RDS, …) requires TLS while a local container does
not, so the SSL context is derived from the host in DATABASE_URL unless
DATABASE_SSL forces it either way.
"""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal", None, ""}


def build_connect_args(database_url: str, mode: str) -> dict[str, Any]:
    """Return asyncpg connect args for the configured TLS mode."""
    if mode == "disable":
        return {}

    if mode == "auto":
        host = make_url(database_url).host
        if host in _LOCAL_HOSTS:
            return {}

    import ssl

    context = ssl.create_default_context()
    # Managed Postgres endpoints commonly present a certificate chain the
    # client cannot pin without downloading the provider's root, so verify
    # transport encryption without hostname pinning.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return {"ssl": context}


engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    connect_args=build_connect_args(settings.database_url, settings.database_ssl),
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
