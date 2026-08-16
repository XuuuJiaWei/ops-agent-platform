"""Small seams shared by benchmark adapters and the agent runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from ops_pilot.config.settings import Settings


class TextAgent(Protocol):
    """The complete runtime interface a benchmark adapter may depend on."""

    async def ainvoke_text(
        self,
        text: str,
        *,
        protocol: str,
        thread_id: str | None = None,
        run_id: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> str: ...

    async def aclose(self) -> None: ...


RuntimeFactory = Callable[[Settings], Awaitable[TextAgent]]
