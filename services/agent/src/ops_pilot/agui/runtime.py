"""AG-UI/CopilotKit runtime extension."""

from __future__ import annotations

from typing import Any

from ops_pilot.runtime.spec import RuntimeSpec


class CopilotKitRuntimeExtension:
    @property
    def tools(self) -> tuple[Any, ...]:
        return ()

    @property
    def prompt_fragments(self) -> tuple[str, ...]:
        return ()

    @property
    def middleware(self) -> tuple[Any, ...]:
        from copilotkit import CopilotKitMiddleware

        return (CopilotKitMiddleware(),)

    async def aclose(self) -> None:
        return None


async def create_copilotkit_runtime_extension(_: RuntimeSpec) -> CopilotKitRuntimeExtension:
    return CopilotKitRuntimeExtension()
