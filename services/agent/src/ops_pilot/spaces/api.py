"""Read-only HTTP projection for the Space canvas."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from ops_pilot.spaces.models import Space, SpaceSummary
from ops_pilot.spaces.repository import SpaceNotFoundError, SpaceRepository


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

    return router
