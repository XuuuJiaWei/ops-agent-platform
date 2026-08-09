"""Space repository selection aligned with the runtime persistence backend."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ops_pilot.config.settings import Settings
from ops_pilot.spaces.postgres import PostgresSpaceRepository
from ops_pilot.spaces.repository import MemorySpaceRepository, SpaceRepository


async def create_space_repository(
    settings: Settings,
) -> tuple[SpaceRepository, Callable[[], Awaitable[None]] | None]:
    if settings.persistence_backend != "postgres":
        return MemorySpaceRepository(), None

    database_url = settings.psycopg_database_url()
    if not database_url:
        raise RuntimeError("persistence.database_url is required for the postgres backend")

    repository, closer = await PostgresSpaceRepository.open(
        database_url,
        namespace=settings.assistant_id,
        setup=settings.persistence_setup_on_start,
    )
    return repository, closer
