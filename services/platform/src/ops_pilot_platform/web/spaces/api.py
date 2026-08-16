"""HTTP interface used by CopilotKit frontend tools and the Space canvas."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ops_pilot_platform.web.spaces.models import (
    CardBinding,
    CardContent,
    CardDraft,
    CardSize,
    CardType,
    Space,
    SpaceSummary,
)
from ops_pilot_platform.web.spaces.repository import SpaceError, SpaceNotFoundError, SpaceRepository


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSpaceRequest(_Request):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class UpdateCardRequest(_Request):
    content: CardContent
    card_type: CardType | None = None
    subtitle: str | None = Field(default=None, max_length=240)
    binding: CardBinding | None = None


class RenameCardRequest(_Request):
    title: str = Field(min_length=1, max_length=160)


class ResizeCardRequest(_Request):
    size: CardSize


class ReorderCardsRequest(_Request):
    card_ids: list[str]


def create_spaces_router(get_repository: Callable[[], SpaceRepository]) -> APIRouter:
    router = APIRouter(prefix="/spaces", tags=["spaces"])

    @router.get("", response_model=list[SpaceSummary])
    async def list_spaces() -> list[SpaceSummary]:
        return await get_repository().list_spaces()

    @router.get("/{space_id}", response_model=Space)
    async def get_space(space_id: str) -> Space:
        try:
            return await get_repository().get_space(space_id)
        except SpaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("", response_model=Space, status_code=status.HTTP_201_CREATED)
    async def create_space(request: CreateSpaceRequest) -> Space:
        return await get_repository().create_space(name=request.name, description=request.description)

    @router.post("/{space_id}/cards", response_model=Space, status_code=status.HTTP_201_CREATED)
    async def add_card(space_id: str, card: CardDraft) -> Space:
        return await _mutation(lambda: get_repository().add_card(space_id, card))

    @router.put("/{space_id}/cards/{card_id}", response_model=Space)
    async def update_card(space_id: str, card_id: str, request: UpdateCardRequest) -> Space:
        return await _mutation(
            lambda: get_repository().update_card(
                space_id,
                card_id,
                content=request.content,
                card_type=request.card_type,
                subtitle=request.subtitle,
                binding=request.binding,
            )
        )

    @router.put("/{space_id}/cards/{card_id}/title", response_model=Space)
    async def rename_card(space_id: str, card_id: str, request: RenameCardRequest) -> Space:
        return await _mutation(lambda: get_repository().rename_card(space_id, card_id, request.title))

    @router.put("/{space_id}/cards/{card_id}/size", response_model=Space)
    async def resize_card(space_id: str, card_id: str, request: ResizeCardRequest) -> Space:
        return await _mutation(lambda: get_repository().resize_card(space_id, card_id, request.size))

    @router.delete("/{space_id}/cards/{card_id}", response_model=Space)
    async def remove_card(space_id: str, card_id: str) -> Space:
        return await _mutation(lambda: get_repository().remove_card(space_id, card_id))

    @router.put("/{space_id}/cards-order", response_model=Space)
    async def reorder_cards(space_id: str, request: ReorderCardsRequest) -> Space:
        return await _mutation(lambda: get_repository().reorder_cards(space_id, request.card_ids))

    return router


async def _mutation(operation: Callable[[], Awaitable[Space]]) -> Space:
    try:
        return await operation()
    except SpaceError as exc:
        status_code = status.HTTP_404_NOT_FOUND if exc.code in {"space_not_found", "card_not_found"} else 409
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)}) from exc
