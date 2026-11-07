"""Async SQLAlchemy engine and session factory for db.

The engine is created lazily so importing this module never opens a connection
(safe for processes that may run without a database configured).
"""

import asyncio

from env.db import env
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

_engine: AsyncEngine | None = None
_engine_loop: asyncio.AbstractEventLoop | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None
_readiness_engine: AsyncEngine | None = None
_readiness_engine_loop: asyncio.AbstractEventLoop | None = None


def _current_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None

# Keep below the API readiness probe's timeout (3s), or the probe gives up first and a reachable
# database reads as unready.
_PING_TIMEOUT_S = 2.0


def get_engine() -> AsyncEngine:
    # An AsyncEngine is bound to the event loop it first ran on; reusing it on another loop
    # (e.g. two asyncio.run() calls in one CLI process) raises "attached to a different loop".
    # Recreate the engine when the running loop changed (short-lived CLI processes just drop it).
    global _engine, _engine_loop
    loop = _current_loop()
    if _engine is None or _engine_loop is not loop:
        _engine = create_async_engine(
            env.async_database_url,
            echo=env.db_echo,
            pool_size=env.db_pool_size,
            max_overflow=env.db_max_overflow,
            pool_pre_ping=env.db_pool_pre_ping,
        )
        _engine_loop = loop
        global _session_maker
        _session_maker = None
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_maker


def _get_readiness_engine() -> AsyncEngine:
    """``NullPool`` so this engine connects per call and can never queue behind the app pool."""
    global _readiness_engine, _readiness_engine_loop
    loop = _current_loop()
    if _readiness_engine is None or _readiness_engine_loop is not loop:
        _readiness_engine = create_async_engine(
            env.async_database_url,
            echo=env.db_echo,
            poolclass=NullPool,
        )
        _readiness_engine_loop = loop
    return _readiness_engine


async def ping(timeout_s: float = _PING_TIMEOUT_S) -> bool:
    """Whether the database answers through the application pool. Never raises.

    Shares the request path's pool, so ``False`` means unreachable OR saturated. That
    ambiguity suits ``/api/health``, which only reports; probes need ``readiness_ping``.
    """
    try:
        async with asyncio.timeout(timeout_s):
            async with get_session_maker()() as session:
                await session.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def readiness_ping(timeout_s: float = _PING_TIMEOUT_S) -> bool:
    """Whether Postgres is reachable from this pod. Never raises. Not a duplicate of ``ping``.

    Readiness gates traffic, so it must not answer "this pod is busy". On the shared pool it
    would: a saturated replica marks itself unready, sheds load onto its peers, saturates
    them, and takes the service down without Postgres ever failing.
    """
    try:
        async with asyncio.timeout(timeout_s):
            async with _get_readiness_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def dispose_engine() -> None:
    global _engine, _engine_loop, _session_maker, _readiness_engine, _readiness_engine_loop
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _engine_loop = None
        _session_maker = None
    if _readiness_engine is not None:
        await _readiness_engine.dispose()
        _readiness_engine = None
        _readiness_engine_loop = None
