"""Async SQLAlchemy engine + session factory.

Lifecycle: the orchestrator's lifespan hook calls `init_engine()` at startup
and `shutdown_engine()` at shutdown. Repositories pull a session via
`get_session()` inside FastAPI dependencies (or use `async_session_factory`
directly outside the request scope).
"""
from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from orchestrator.app.config import settings


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(dsn: str | None = None) -> AsyncEngine:
    """Initialise the global async engine. Safe to call multiple times."""
    global _engine, _sessionmaker
    if _engine is not None:
        return _engine
    _engine = create_async_engine(
        dsn or settings.postgres_dsn,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        future=True,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def shutdown_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def async_session_factory() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — yields a session and commits on exit."""
    factory = async_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
