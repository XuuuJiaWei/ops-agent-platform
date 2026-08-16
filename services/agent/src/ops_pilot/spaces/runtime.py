"""Spaces runtime extension, owned by hosts that expose the Spaces feature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ops_pilot.config.settings import Settings
from ops_pilot.spaces.factory import create_space_repository
from ops_pilot.spaces.repository import SpaceRepository
from ops_pilot.spaces.tools import build_space_tools

_PROMPT = """You can create agent-native visual experiences with Space tools.
Use render_ui for a transient card that belongs in the current conversation.
Use create_space and the card-in-space tools when the user wants a persistent dashboard.
Before changing an existing Space, use list_spaces or get_space when you do not already have its current ids.
Cards are declarative data: choose the card type that best communicates the result and keep labels concise.
For a live (auto-refreshing) card, set a binding to a read-only source_tool; the backend stores only the tool's
raw response, and a binding.transform (a small JS function transform(raw) replayed deterministically in the
frontend sandbox) normalizes that raw output into content. Call the source tool once first to see its real
shape, then write the transform — one JS transform is the single normalization layer for every source, so do
not maintain per-source query languages or decoders. After writing a transform, ALWAYS call
validate_card_transform (pass the transform code, the raw you just observed from the source tool, and the
card_type) and only add or update the card once it returns ok; if it fails, fix the JS per the message and
re-validate — never persist a transform that has not passed."""


@dataclass
class SpacesRuntimeExtension:
    repository: SpaceRepository
    _closer: Any = None

    @property
    def tools(self) -> tuple[Any, ...]:
        return tuple(build_space_tools(self.repository))

    @property
    def middleware(self) -> tuple[Any, ...]:
        return ()

    @property
    def prompt_fragments(self) -> tuple[str, ...]:
        return (_PROMPT,)

    async def aclose(self) -> None:
        if self._closer is not None:
            await self._closer()


async def create_spaces_runtime_extension(settings: Settings) -> SpacesRuntimeExtension:
    repository, closer = await create_space_repository(settings)
    return SpacesRuntimeExtension(repository=repository, _closer=closer)
