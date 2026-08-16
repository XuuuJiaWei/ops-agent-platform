"""Runtime extension seam for host-specific capabilities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ops_pilot.runtime.spec import RuntimeSpec


class RuntimeExtension(Protocol):
    """Optional capability contributed by a runtime host."""

    @property
    def tools(self) -> Sequence[Any]: ...

    @property
    def middleware(self) -> Sequence[Any]: ...

    @property
    def prompt_fragments(self) -> Sequence[str]: ...

    async def aclose(self) -> None: ...


RuntimeExtensionFactory = Callable[["RuntimeSpec"], Awaitable[RuntimeExtension]]
