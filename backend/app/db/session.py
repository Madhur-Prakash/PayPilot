"""Async engine + session factory, and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _engine_kwargs(url: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "echo": settings.db_echo,
        "pool_pre_ping": True,
        "future": True,
    }
    if url.startswith("sqlite"):
        # SQLite (tests) - a shared in-file/in-memory database with no pooling.
        kwargs["poolclass"] = NullPool
        kwargs["connect_args"] = {"check_same_thread": False}
        return kwargs

    kwargs["pool_size"] = settings.db_pool_size
    kwargs["max_overflow"] = settings.db_max_overflow
    kwargs["pool_recycle"] = 1800

    connect_args: dict[str, Any] = {
        "server_settings": {"application_name": settings.app_name},
        "timeout": 30,
    }
    # Supabase / PgBouncer run in transaction pooling mode, which is incompatible
    # with asyncpg's implicit prepared-statement cache.
    if "pooler.supabase" in url or "pgbouncer=true" in url:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        kwargs["poolclass"] = NullPool
        kwargs.pop("pool_size", None)
        kwargs.pop("max_overflow", None)
    kwargs["connect_args"] = connect_args
    return kwargs


def create_engine(url: str | None = None) -> AsyncEngine:
    target = url or settings.database_url
    return create_async_engine(target, **_engine_kwargs(target))


engine: AsyncEngine = create_engine()

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Commits on success, rolls back on any exception."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional session for scripts, seeders and background work."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def ping_database() -> bool:
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.error("database_unreachable", error_type=type(exc).__name__, detail=str(exc)[:200])
        return False


async def ensure_extensions() -> dict[str, bool]:
    """Best-effort creation of the Postgres extensions the app relies on."""
    from sqlalchemy import text

    results: dict[str, bool] = {}
    if not settings.is_postgres:
        return results
    for extension in ("vector", "pgcrypto"):
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{extension}"'))
            results[extension] = True
        except Exception as exc:
            results[extension] = False
            log.warning("extension_unavailable", extension=extension, detail=str(exc)[:200])
    return results


async def dispose_engine() -> None:
    await engine.dispose()
