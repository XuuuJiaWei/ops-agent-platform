"""A2A task store selection behind a stable factory.

The protocol code always talks to the official ``TaskStore`` interface; only the
backend changes. ``memory`` keeps the in-process store (tasks lost on restart);
``postgres`` uses the SDK's SQLAlchemy-backed ``DatabaseTaskStore`` so A2A tasks
survive restarts alongside the LangGraph checkpoints.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ops_pilot.runtime.spec import PersistenceSpec


async def create_task_store(
    persistence: PersistenceSpec,
) -> tuple[Any, Callable[[], Awaitable[None]] | None]:
    """Build an A2A task store for the configured persistence backend.

    Returns ``(store, closer)``. ``closer`` disposes any owned resources (e.g. a
    SQLAlchemy engine) and must be awaited on shutdown; it is ``None`` for the
    in-memory store, which holds nothing to release.
    """

    if persistence.backend == "postgres":
        return await _create_database_task_store(persistence)
    return _create_memory_task_store(), None


def _create_memory_task_store() -> Any:
    from a2a.server.tasks import InMemoryTaskStore

    return InMemoryTaskStore()


async def _create_database_task_store(
    persistence: PersistenceSpec,
) -> tuple[Any, Callable[[], Awaitable[None]]]:
    from a2a.server.tasks import DatabaseTaskStore
    from sqlalchemy.ext.asyncio import create_async_engine

    url = _sqlalchemy_database_url(persistence.database_url)
    if not url:
        raise RuntimeError("persistence.backend is 'postgres' but DATABASE_URL is not set.")

    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        store = DatabaseTaskStore(engine, create_table=persistence.setup_on_start)
        # initialize() is idempotent; it creates the tasks table when missing.
        await store.initialize()
    except Exception:
        await engine.dispose()
        raise

    async def _close() -> None:
        await engine.dispose()

    return store, _close


def _sqlalchemy_database_url(database_url: str | None) -> str | None:
    if not database_url:
        return None
    if database_url.startswith("postgresql+"):
        normalized = database_url
    elif database_url.startswith("postgresql://"):
        normalized = "postgresql+asyncpg://" + database_url[len("postgresql://") :]
    else:
        return database_url
    return normalized.replace("sslmode=", "ssl=")
