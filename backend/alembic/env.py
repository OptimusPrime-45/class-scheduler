"""Alembic async migration environment.

Built from Alembic's ``async`` template, then wired to our settings + ORM metadata:
* URL comes from ``settings.migration_url`` (a direct, non-pooled Neon endpoint is fine
  for migrations) and is normalized for asyncpg by ``app.db.normalize_async_url``.
* ``target_metadata`` is ``app.db.Base.metadata``; importing ``app.models`` registers
  every table on it so ``--autogenerate`` sees the full schema.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

import app.models  # noqa: F401  — registers all models on Base.metadata
from app.config import settings
from app.db import Base, normalize_async_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Normalize once (driver swap, statement_cache_size=0, ssl) — shared with the app engine.
DB_URL, CONNECT_ARGS = normalize_async_url(settings.migration_url)


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # Postgres ENUM types: create/drop the type alongside its column on the
        # first migration. (autogenerate emits CREATE TYPE inline.)
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Emit SQL without a live connection."""
    _configure(url=DB_URL, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(
        DB_URL,
        connect_args=CONNECT_ARGS,
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
