"""Async engine and session factory.

Hosted Postgres (Supabase, RDS, …) requires TLS while a local container does
not, so the SSL context is derived from the host in DATABASE_URL unless
DATABASE_SSL forces it either way.

The engine also adapts to *which* endpoint the URL points at, because Supabase
publishes three and they do not behave alike:

* ``db.<project>.supabase.co:5432`` — direct. The default, and the only one
  that needs no special handling. It resolves to IPv6 only, so a runtime
  without IPv6 egress (Vercel, AWS Lambda) cannot reach it at all: asyncpg
  fails at connect with ``OSError: [Errno 99] Cannot assign requested address``.
* ``…pooler.supabase.com:5432`` — Supavisor session mode. IPv4, and one backend
  connection per client connection, so prepared statements work unchanged.
* ``…pooler.supabase.com:6543`` — Supavisor transaction mode. IPv4, but a
  connection is handed to a different backend per transaction, which breaks
  asyncpg's named prepared statements and SQLAlchemy's pooling on top of it.
  Usable only with the three settings applied below.
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal", None, ""}

#: Supavisor's transaction-mode port. Session mode is 5432 on the same host.
_TRANSACTION_POOLER_PORT = 6543


def is_transaction_pooled(database_url: str) -> bool:
    """Whether this URL points at a pooler in transaction mode."""
    url = make_url(database_url)
    host = url.host or ""
    return url.port == _TRANSACTION_POOLER_PORT and "pooler." in host


def build_connect_args(database_url: str, mode: str) -> dict[str, Any]:
    """Return asyncpg connect args for the configured TLS mode and endpoint."""
    args: dict[str, Any] = {}

    if is_transaction_pooled(database_url):
        # Transaction mode gives each transaction a different backend, so a
        # statement prepared on one is absent on the next. Turning the cache off
        # is not enough on its own: asyncpg still names its statements, and two
        # clients that land on the same backend collide. An empty name means an
        # unnamed statement, which is never stored server-side.
        args["statement_cache_size"] = 0
        args["prepared_statement_name_func"] = lambda: ""

    if mode == "disable":
        return args

    if mode == "auto":
        host = make_url(database_url).host
        if host in _LOCAL_HOSTS:
            return args

    import ssl

    context = ssl.create_default_context()
    # Managed Postgres endpoints commonly present a certificate chain the
    # client cannot pin without downloading the provider's root, so verify
    # transport encryption without hostname pinning.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    args["ssl"] = context
    return args


def resolve_pool_limits() -> tuple[int, int, str | None]:
    """Pool sizes clamped to what the provider will actually accept.

    A pooler caps *client* connections and refuses the one past the cap —
    Supavisor session mode answers `EMAXCONNSESSION: max clients reached`,
    which arrives mid-run as a failed paper rather than as a wait. The number
    the provider sees is ``pool_size + max_overflow``, not ``pool_size``:
    SQLAlchemy opens an overflow connection whenever the pool is empty instead
    of queueing, so overflow is exactly the setting that walks past the cap.

    Clamping here rather than only warning means a too-large pool degrades into
    tasks waiting on each other, which is recoverable, instead of connections
    the provider rejects, which is not.
    """
    pool_size = max(1, settings.db_pool_size)
    overflow = max(0, settings.db_max_overflow)
    if settings.db_max_clients <= 0:
        return pool_size, overflow, None

    budget = max(1, settings.db_max_clients - max(0, settings.db_client_headroom))
    if pool_size + overflow <= budget:
        return pool_size, overflow, None

    clamped_size = min(pool_size, budget)
    clamped_overflow = budget - clamped_size
    warning = (
        f"DB_POOL_SIZE + DB_MAX_OVERFLOW is {pool_size + overflow}, above the "
        f"{budget} connections this process may hold "
        f"(DB_MAX_CLIENTS={settings.db_max_clients} less "
        f"DB_CLIENT_HEADROOM={settings.db_client_headroom}); "
        f"clamped to pool_size={clamped_size}, max_overflow={clamped_overflow}"
    )
    return clamped_size, clamped_overflow, warning


def build_engine_kwargs(database_url: str) -> dict[str, Any]:
    """Pool settings for this endpoint.

    Behind a transaction pooler, SQLAlchemy holding its own long-lived
    connections is redundant at best — the pooler is already the pool, and a
    checked-out connection has no stable backend to keep state on. NullPool
    hands every session a fresh connection and lets Supavisor do the pooling.
    """
    if is_transaction_pooled(database_url):
        return {"poolclass": NullPool}

    pool_size, overflow, _ = resolve_pool_limits()
    return {
        "pool_size": pool_size,
        "max_overflow": overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle,
        # LIFO hands work back to the connection used most recently, so a burst
        # that opened overflow connections lets the rest go idle and be recycled
        # instead of keeping every slot warm against the provider's cap.
        "pool_use_lifo": True,
        "pool_pre_ping": True,
    }


#: Non-null when the configured pool would not fit the provider's client cap.
#: Reported by /health/config, because the symptom (papers failing one by one)
#: does not look like a configuration fault from the UI.
pool_warning: str | None = (
    None if is_transaction_pooled(settings.database_url) else resolve_pool_limits()[2]
)

if pool_warning:
    logger.warning("%s", pool_warning)


engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args=build_connect_args(settings.database_url, settings.database_ssl),
    **build_engine_kwargs(settings.database_url),
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
