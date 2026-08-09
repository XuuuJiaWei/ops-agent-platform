"""Agent tools for transient visualizations and persistent Spaces."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from ops_pilot.spaces.models import (
    CardContent,
    CardDraft,
    CardSize,
    CardType,
    Space,
    SpaceCard,
    utc_now,
)
from ops_pilot.spaces.repository import SpaceError, SpaceRepository


class RenderUiArgs(BaseModel):
    """Render one transient card inside the conversation."""

    model_config = ConfigDict(extra="forbid")
    card: CardDraft


class CreateSpaceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class SpaceIdArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    space_id: str = Field(min_length=1)


class AddCardArgs(SpaceIdArgs):
    card: CardDraft


class UpdateCardArgs(SpaceIdArgs):
    card_id: str = Field(min_length=1)
    content: CardContent
    card_type: CardType | None = None
    subtitle: str | None = Field(default=None, max_length=240)


class RenameCardArgs(SpaceIdArgs):
    card_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=160)


class ResizeCardArgs(SpaceIdArgs):
    card_id: str = Field(min_length=1)
    size: CardSize


class RemoveCardArgs(SpaceIdArgs):
    card_id: str = Field(min_length=1)


class ReorderCardsArgs(SpaceIdArgs):
    card_ids: list[str] = Field(description="Every card id exactly once, in the desired order")


def build_space_tools(repository: SpaceRepository) -> tuple[BaseTool, ...]:
    """Bind the stable public tool contract to one repository instance."""

    @tool("render_ui", args_schema=RenderUiArgs)
    async def render_ui(card: CardDraft) -> dict[str, Any]:
        """Render a transient KPI, table, chart, details, object list, or markdown card inline."""

        now = utc_now()
        rendered = SpaceCard(
            **card.model_dump(),
            id=str(uuid4()),
            created_at=now,
            updated_at=now,
        )
        return {"ok": True, "transient": True, "card": rendered.model_dump(mode="json")}

    @tool("create_space", args_schema=CreateSpaceArgs)
    async def create_space(name: str, description: str | None = None) -> dict[str, Any]:
        """Create a persistent Space that can hold reusable visualization cards."""

        return await _run(lambda: repository.create_space(name=name, description=description))

    @tool("add_card_to_space", args_schema=AddCardArgs)
    async def add_card_to_space(space_id: str, card: CardDraft) -> dict[str, Any]:
        """Add a visualization card to an existing Space."""

        return await _run(lambda: repository.add_card(space_id, card))

    @tool("update_card_in_space", args_schema=UpdateCardArgs)
    async def update_card_in_space(
        space_id: str,
        card_id: str,
        content: CardContent,
        card_type: CardType | None = None,
        subtitle: str | None = None,
    ) -> dict[str, Any]:
        """Update the content and optional type or subtitle of an existing Space card."""

        return await _run(
            lambda: repository.update_card(
                space_id,
                card_id,
                content=content,
                card_type=card_type,
                subtitle=subtitle,
            )
        )

    @tool("rename_card", args_schema=RenameCardArgs)
    async def rename_card_tool(space_id: str, card_id: str, title: str) -> dict[str, Any]:
        """Rename one card in a Space without changing its content."""

        return await _run(lambda: repository.rename_card(space_id, card_id, title))

    @tool("resize_card", args_schema=ResizeCardArgs)
    async def resize_card_tool(space_id: str, card_id: str, size: CardSize) -> dict[str, Any]:
        """Change a Space card's responsive display size."""

        return await _run(lambda: repository.resize_card(space_id, card_id, size))

    @tool("remove_card_from_space", args_schema=RemoveCardArgs)
    async def remove_card_from_space(space_id: str, card_id: str) -> dict[str, Any]:
        """Remove one card from a Space."""

        return await _run(lambda: repository.remove_card(space_id, card_id))

    @tool("reorder_cards_in_space", args_schema=ReorderCardsArgs)
    async def reorder_cards_in_space(space_id: str, card_ids: list[str]) -> dict[str, Any]:
        """Set the complete display order of cards in a Space."""

        return await _run(lambda: repository.reorder_cards(space_id, card_ids))

    @tool("list_spaces")
    async def list_spaces() -> dict[str, Any]:
        """List persistent Spaces with card counts and update timestamps."""

        try:
            spaces = await repository.list_spaces()
            return {"ok": True, "spaces": [space.model_dump(mode="json") for space in spaces]}
        except SpaceError as exc:
            return _error(exc)

    @tool("get_space", args_schema=SpaceIdArgs)
    async def get_space(space_id: str) -> dict[str, Any]:
        """Read a Space and all of its current cards."""

        return await _run(lambda: repository.get_space(space_id))

    return (
        render_ui,
        create_space,
        add_card_to_space,
        update_card_in_space,
        rename_card_tool,
        resize_card_tool,
        remove_card_from_space,
        reorder_cards_in_space,
        list_spaces,
        get_space,
    )


async def _run(operation: Callable[[], Awaitable[Space]]) -> dict[str, Any]:
    try:
        space = await operation()
        return {"ok": True, "space": space.model_dump(mode="json")}
    except SpaceError as exc:
        return _error(exc)


def _error(exc: SpaceError) -> dict[str, Any]:
    return {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
