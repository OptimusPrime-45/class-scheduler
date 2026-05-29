"""Async SQLAlchemy engine / session, and the declarative ``Base``.

Neon quirks handled here (see readme Phase 0 pitfalls):
* The app talks to Neon through PgBouncer (the ``-pooler`` endpoint). asyncpg caches
  prepared statements by default, which breaks under PgBouncer's transaction pooling.
  We disable it with ``statement_cache_size=0``.
* Neon URLs carry ``?sslmode=require`` / ``channel_binding`` query params that asyncpg
  does not understand on the DSN; we strip them and pass SSL via ``connect_args`` instead.
* Neon scales to zero, so a connection after idle may hit a cold start —
  ``pool_pre_ping=True`` transparently recycles dead connections.
"""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit, urlunsplit

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Deterministic constraint/index names so Alembic autogenerate diffs are stable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base for all ORM models. ``Base.metadata`` is Alembic's target."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# Query params that belong to libpq/psycopg, not asyncpg — strip from the DSN and
# re-express through connect_args where needed.
_PG_ONLY_QUERY_KEYS = {"sslmode", "channel_binding", "options"}


def normalize_async_url(url: str) -> tuple[str, dict]:
    """Return an asyncpg-compatible URL and the matching ``connect_args``.

    * Forces the ``postgresql+asyncpg`` driver.
    * Disables the prepared-statement cache (PgBouncer safety).
    * Translates ``sslmode=require`` into asyncpg's ``ssl=True``.
    """
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    elif url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]

    parts = urlsplit(url)
    query_pairs = [
        (k, v)
        for segment in parts.query.split("&")
        if segment
        for k, _, v in [segment.partition("=")]
    ]
    sslmode = next((v for k, v in query_pairs if k == "sslmode"), None)
    kept = [(k, v) for k, v in query_pairs if k not in _PG_ONLY_QUERY_KEYS]
    clean_url = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)
    )

    connect_args: dict = {"statement_cache_size": 0}
    # Neon always requires TLS; honour an explicit sslmode but default to on for asyncpg
    # whenever a remote host is configured.
    if sslmode in {"require", "verify-ca", "verify-full", "prefer", "allow", None}:
        if sslmode is not None or parts.hostname not in {None, "localhost", "127.0.0.1"}:
            connect_args["ssl"] = True
    if sslmode == "disable":
        connect_args.pop("ssl", None)

    return clean_url, connect_args


_url, _connect_args = normalize_async_url(settings.database_url)

engine = create_async_engine(
    _url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    echo=False,
)

# expire_on_commit=False keeps attributes usable after commit (handy in async request flows).
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncSession:
    """FastAPI dependency yielding a request-scoped async session."""
    async with SessionLocal() as session:
        yield session
