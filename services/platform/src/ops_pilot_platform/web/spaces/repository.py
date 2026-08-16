"""Space repository interface, domain mutations, and memory adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

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


class SpaceError(RuntimeError):
    code = "space_error"


class SpaceNotFoundError(SpaceError):
    code = "space_not_found"


class CardNotFoundError(SpaceError):
    code = "card_not_found"


class InvalidCardOrderError(SpaceError):
    code = "invalid_card_order"


class SpaceRepository(Protocol):
    async def create_space(self, name: str, description: str | None = None) -> Space: ...

    async def list_spaces(self) -> list[SpaceSummary]: ...

    async def get_space(self, space_id: str) -> Space: ...

    async def add_card(self, space_id: str, card: CardDraft) -> Space: ...

    async def update_card(
        self,
        space_id: str,
        card_id: str,
        *,
        content: CardContent,
        card_type: CardType | None = None,
        subtitle: str | None = None,
        binding: CardBinding | None = None,
    ) -> Space: ...

    async def rename_card(self, space_id: str, card_id: str, title: str) -> Space: ...

    async def resize_card(self, space_id: str, card_id: str, size: CardSize) -> Space: ...

    async def remove_card(self, space_id: str, card_id: str) -> Space: ...

    async def reorder_cards(self, space_id: str, ordered_card_ids: list[str]) -> Space: ...

    async def list_live_cards(self) -> list[tuple[str, SpaceCard]]: ...

    async def apply_refresh(
        self,
        space_id: str,
        card_id: str,
        *,
        raw_snapshot: Any | None,
        status: RefreshStatus,
        last_error: str | None,
        last_refreshed_at: datetime | None,
    ) -> None: ...


SpaceMutation = Callable[[Space], Space]


class MemorySpaceRepository:
    """Process-local adapter used when durable persistence is disabled."""

    def __init__(self) -> None:
        self._spaces: dict[str, Space] = {}
        self._lock = asyncio.Lock()

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
        async with self._lock:
            self._spaces[space.id] = space
        return _copy(space)

    async def list_spaces(self) -> list[SpaceSummary]:
        async with self._lock:
            spaces = sorted(self._spaces.values(), key=lambda item: item.updated_at, reverse=True)
            return [SpaceSummary.from_space(_copy(space)) for space in spaces]

    async def get_space(self, space_id: str) -> Space:
        async with self._lock:
            return _copy(_require_space(self._spaces.get(space_id), space_id))

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
        async with self._lock:
            return [
                (space.id, card.model_copy(deep=True))
                for space in self._spaces.values()
                for card in space.cards
                if card.binding is not None
            ]

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

    async def _mutate(self, space_id: str, mutation: SpaceMutation) -> Space:
        async with self._lock:
            current = _require_space(self._spaces.get(space_id), space_id)
            updated = mutation(current)
            self._spaces[space_id] = updated
            return _copy(updated)


def add_card(space: Space, draft: CardDraft) -> Space:
    now = utc_now()
    card = SpaceCard(
        **draft.model_dump(),
        id=str(uuid4()),
        created_at=now,
        updated_at=now,
    )
    return _updated_space(space, cards=[*space.cards, card], now=now)


def update_card(
    space: Space,
    card_id: str,
    *,
    content: CardContent,
    card_type: CardType | None,
    subtitle: str | None,
    binding: CardBinding | None = None,
) -> Space:
    current = _find_card(space, card_id)
    now = utc_now()
    draft = CardDraft(
        type=card_type or current.type,
        title=current.title,
        subtitle=current.subtitle if subtitle is None else subtitle,
        size=current.size,
        content=content,
        binding=current.binding if binding is None else binding,
    )
    replacement = SpaceCard(
        **draft.model_dump(),
        id=current.id,
        created_at=current.created_at,
        updated_at=now,
        refresh_status=current.refresh_status,
        last_refreshed_at=current.last_refreshed_at,
        last_error=current.last_error,
        raw_snapshot=current.raw_snapshot,
    )
    return _updated_space(space, cards=_replace_card(space.cards, replacement), now=now)


def apply_card_refresh(
    space: Space,
    card_id: str,
    *,
    raw_snapshot: Any | None,
    status: RefreshStatus,
    last_error: str | None,
    last_refreshed_at: datetime | None,
) -> Space:
    """Write resolver output back onto a single card without bumping version.

    Unlike ``update_card`` this deliberately does NOT go through
    ``_updated_space`` — high-frequency refreshes must not inflate the space
    version or change its semantic ``updated_at``. Only the target card's raw
    snapshot and refresh-status fields are touched. ``raw_snapshot=None``
    preserves the last-good snapshot (used on error).
    """

    current = _find_card(space, card_id)
    updates: dict[str, object] = {
        "refresh_status": status,
        "last_error": last_error,
        "last_refreshed_at": last_refreshed_at,
        "updated_at": last_refreshed_at or utc_now(),
    }
    if raw_snapshot is not None:
        updates["raw_snapshot"] = raw_snapshot
    replacement = current.model_copy(update=updates)
    return space.model_copy(update={"cards": _replace_card(space.cards, replacement)}, deep=True)


def rename_card(space: Space, card_id: str, title: str) -> Space:
    current = _find_card(space, card_id)
    now = utc_now()
    return _updated_space(
        space,
        cards=_replace_card(space.cards, current.model_copy(update={"title": title, "updated_at": now})),
        now=now,
    )


def resize_card(space: Space, card_id: str, size: CardSize) -> Space:
    current = _find_card(space, card_id)
    now = utc_now()
    return _updated_space(
        space,
        cards=_replace_card(space.cards, current.model_copy(update={"size": size, "updated_at": now})),
        now=now,
    )


def remove_card(space: Space, card_id: str) -> Space:
    _find_card(space, card_id)
    now = utc_now()
    return _updated_space(space, cards=[card for card in space.cards if card.id != card_id], now=now)


def reorder_cards(space: Space, ordered_card_ids: list[str]) -> Space:
    existing_ids = [card.id for card in space.cards]
    if len(ordered_card_ids) != len(set(ordered_card_ids)) or set(ordered_card_ids) != set(existing_ids):
        raise InvalidCardOrderError("ordered_card_ids must contain every current card id exactly once.")
    cards_by_id = {card.id: card for card in space.cards}
    return _updated_space(space, cards=[cards_by_id[card_id] for card_id in ordered_card_ids], now=utc_now())


def _updated_space(space: Space, *, cards: list[SpaceCard], now: datetime) -> Space:
    return space.model_copy(update={"cards": cards, "version": space.version + 1, "updated_at": now}, deep=True)


def _replace_card(cards: list[SpaceCard], replacement: SpaceCard) -> list[SpaceCard]:
    return [replacement if card.id == replacement.id else card for card in cards]


def _find_card(space: Space, card_id: str) -> SpaceCard:
    card = next((card for card in space.cards if card.id == card_id), None)
    if card is None:
        raise CardNotFoundError(f"Card '{card_id}' was not found in space '{space.id}'.")
    return card


def _require_space(space: Space | None, space_id: str) -> Space:
    if space is None:
        raise SpaceNotFoundError(f"Space '{space_id}' was not found.")
    return space


def _copy(space: Space) -> Space:
    return space.model_copy(deep=True)
