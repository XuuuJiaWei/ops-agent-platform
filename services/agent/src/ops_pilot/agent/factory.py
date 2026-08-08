"""Public factory functions for the shared agent runtime."""

from __future__ import annotations

import asyncio

from ops_pilot.agent.runtime import AgentRuntime, build_agent_runtime
from ops_pilot.config.settings import Settings

# The async factory is the runtime builder itself; the name is kept as the
# package's stable public entrypoint.
create_agent_runtime_async = build_agent_runtime


def create_agent_runtime(
    settings: Settings | None = None,
    *,
    attach_checkpointer: bool = True,
) -> AgentRuntime:
    """Synchronously build the runtime for LangGraph graph imports and CLI use."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            build_agent_runtime(
                settings,
                attach_checkpointer=attach_checkpointer,
            )
        )
    raise RuntimeError(
        "create_agent_runtime() cannot run inside an active event loop; use create_agent_runtime_async() instead."
    )
