"""Runtime extension seam for host-specific capabilities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from ops_pilot.config.settings import Settings


class RuntimeExtension(Protocol):
    """Optional capability contributed by a runtime host."""

    @property
    def tools(self) -> Sequence[Any]: ...

    @property
    def middleware(self) -> Sequence[Any]: ...

    @property
    def prompt_fragments(self) -> Sequence[str]: ...

    async def aclose(self) -> None: ...


RuntimeExtensionFactory = Callable[[Settings], Awaitable[RuntimeExtension]]
