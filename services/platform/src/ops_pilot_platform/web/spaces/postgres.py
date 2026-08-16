"""PostgreSQL implementation of the Space aggregate repository."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ops_pilot_platform.web.spaces.models import (
    CardBinding,
    CardContent,
    CardDraft,
    CardSize,
    CardType,
    RefreshStatus,
    Space,
    SpaceCard,
    SpaceSummary,
    utc_now,
)
from ops_pilot_platform.web.spaces.repository import (
    SpaceNotFoundError,
    SpaceRepository,
    add_card,
    apply_card_refresh,
    remove_card,
    rename_card,
    reorder_cards,
    resize_card,
    update_card,
)


class PostgresSpaceRepository(SpaceRepository):
    """Store each Space as one transactionally updated JSONB aggregate."""

    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[DictRow]], *, namespace: str) -> None:
        self._pool = pool
        self._namespace = namespace

    @classmethod
    async def open(
        cls,
        database_url: str,
        *,
        namespace: str,
        setup: bool,
    ) -> tuple[PostgresSpaceRepository, Callable[[], Awaitable[None]]]:
        pool: AsyncConnectionPool[AsyncConnection[DictRow]] = AsyncConnectionPool(
            conninfo=database_url,
            open=False,
            connection_class=AsyncConnection[DictRow],
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        await pool.open(wait=True)
        repository = cls(pool, namespace=namespace)
        try:
            if setup:
                await repository.setup()
        except Exception:
            await pool.close()
            raise

        async def _close() -> None:
            await pool.close()

        return repository, _close

    async def setup(self) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ops_pilot_spaces (
                    namespace TEXT NOT NULL,
                    id UUID NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    cards JSONB NOT NULL DEFAULT '[]'::jsonb,
                    version BIGINT NOT NULL DEFAULT 1,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (namespace, id)
                )
                """
            )
            await connection.execute(
                """
                CREATE INDEX IF NOT EXISTS ops_pilot_spaces_updated_idx
                ON ops_pilot_spaces (namespace, updated_at DESC)
                """
            )

    async def create_space(self, name: str, description: str | None = None) -> Space:
        now = utc_now()
        space = Space(
            id=str(uuid4()),
            name=name,
            description=description,
            cards=[],
            version=1,
            created_at=now,
            updated_at=now,
        )
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO ops_pilot_spaces
                    (namespace, id, name, description, cards, version, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self._namespace,
                    space.id,
                    space.name,
                    space.description,
                    Jsonb([]),
                    space.version,
                    space.created_at,
                    space.updated_at,
                ),
            )
        return space

    async def list_spaces(self) -> list[SpaceSummary]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT id, name, description, jsonb_array_length(cards) AS card_count,
                       version, created_at, updated_at
                FROM ops_pilot_spaces
                WHERE namespace = %s
                ORDER BY updated_at DESC, name ASC
                """,
                (self._namespace,),
            )
            rows = await cursor.fetchall()
        return [
            SpaceSummary(
                id=str(row["id"]),
                name=row["name"],
                description=row["description"],
                card_count=row["card_count"],
                version=row["version"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def get_space(self, space_id: str) -> Space:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT id, name, description, cards, version, created_at, updated_at
                FROM ops_pilot_spaces
                WHERE namespace = %s AND id = %s
                """,
                (self._namespace, space_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise SpaceNotFoundError(space_id)
        return _row_to_space(row)

    async def add_card(self, space_id: str, card: CardDraft) -> Space:
        return await self._mutate(space_id, lambda space: add_card(space, card))

    async def update_card(
        self,
        space_id: str,
        card_id: str,
        *,
        content: CardContent,
        card_type: CardType | None = None,
        subtitle: str | None = None,
        binding: CardBinding | None = None,
    ) -> Space:
        return await self._mutate(
            space_id,
            lambda space: update_card(
                space,
                card_id,
                content=content,
                card_type=card_type,
                subtitle=subtitle,
                binding=binding,
            ),
        )

    async def rename_card(self, space_id: str, card_id: str, title: str) -> Space:
        return await self._mutate(space_id, lambda space: rename_card(space, card_id, title))

    async def resize_card(self, space_id: str, card_id: str, size: CardSize) -> Space:
        return await self._mutate(space_id, lambda space: resize_card(space, card_id, size))

    async def remove_card(self, space_id: str, card_id: str) -> Space:
        return await self._mutate(space_id, lambda space: remove_card(space, card_id))

    async def reorder_cards(self, space_id: str, ordered_card_ids: list[str]) -> Space:
        return await self._mutate(space_id, lambda space: reorder_cards(space, ordered_card_ids))

    async def list_live_cards(self) -> list[tuple[str, SpaceCard]]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT id, name, description, cards, version, created_at, updated_at
                FROM ops_pilot_spaces
                WHERE namespace = %s AND cards @> '[{"binding": {}}]'::jsonb
                """,
                (self._namespace,),
            )
            rows = await cursor.fetchall()
        result: list[tuple[str, SpaceCard]] = []
        for row in rows:
            space = _row_to_space(row)
            result.extend((space.id, card) for card in space.cards if card.binding is not None)
        return result

    async def apply_refresh(
        self,
        space_id: str,
        card_id: str,
        *,
        raw_snapshot: Any | None,
        status: RefreshStatus,
        last_error: str | None,
        last_refreshed_at: datetime | None,
    ) -> None:
        await self._mutate(
            space_id,
            lambda space: apply_card_refresh(
                space,
                card_id,
                raw_snapshot=raw_snapshot,
                status=status,
                last_error=last_error,
                last_refreshed_at=last_refreshed_at,
            ),
        )

    async def _mutate(self, space_id: str, mutation: Callable[[Space], Space]) -> Space:
        async with self._pool.connection() as connection, connection.transaction():
            cursor = await connection.execute(
                """
                SELECT id, name, description, cards, version, created_at, updated_at
                FROM ops_pilot_spaces
                WHERE namespace = %s AND id = %s
                FOR UPDATE
                """,
                (self._namespace, space_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise SpaceNotFoundError(space_id)
            updated = mutation(_row_to_space(row))
            await connection.execute(
                """
                UPDATE ops_pilot_spaces
                SET name = %s, description = %s, cards = %s, version = %s, updated_at = %s
                WHERE namespace = %s AND id = %s
                """,
                (
                    updated.name,
                    updated.description,
                    Jsonb([card.model_dump(mode="json") for card in updated.cards]),
                    updated.version,
                    updated.updated_at,
                    self._namespace,
                    space_id,
                ),
            )
        return updated


def _row_to_space(row: dict[str, Any]) -> Space:
    return Space.model_validate(
        {
            "id": str(row["id"]),
            "name": row["name"],
            "description": row["description"],
            "cards": row["cards"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )
