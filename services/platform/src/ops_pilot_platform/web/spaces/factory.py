"""Space repository selection aligned with the runtime persistence backend."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ops_pilot.runtime.spec import PersistenceSpec

from ops_pilot_platform.web.spaces.postgres import PostgresSpaceRepository
from ops_pilot_platform.web.spaces.repository import MemorySpaceRepository, SpaceRepository


async def create_space_repository(
    persistence: PersistenceSpec,
    *,
    namespace: str,
) -> tuple[SpaceRepository, Callable[[], Awaitable[None]] | None]:
    if persistence.backend != "postgres":
        return MemorySpaceRepository(), None

    database_url = _psycopg_database_url(persistence.database_url)
    if not database_url:
        raise RuntimeError("persistence.database_url is required for the postgres backend")

    repository, closer = await PostgresSpaceRepository.open(
        database_url,
        namespace=namespace,
        setup=persistence.setup_on_start,
    )
    return repository, closer


def _psycopg_database_url(database_url: str | None) -> str | None:
    if not database_url or not database_url.startswith("postgresql+"):
        return database_url
    rest = database_url[len("postgresql") :]
    return "postgresql" + rest[rest.index("://") :]
