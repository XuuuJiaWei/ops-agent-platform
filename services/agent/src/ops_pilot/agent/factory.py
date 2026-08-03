"""Public factory functions for the shared agent runtime."""

from __future__ import annotations

import asyncio

from ops_pilot.agent.runtime import AgentRuntime, build_agent_runtime
from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.config.settings import Settings


async def create_agent_runtime_async(
    settings: Settings | None = None,
    *,
    dynamic_mcp_config: MCPConfig | None = None,
    use_memory_checkpointer: bool = True,
) -> AgentRuntime:
    return await build_agent_runtime(
        settings,
        dynamic_mcp_config=dynamic_mcp_config,
        use_memory_checkpointer=use_memory_checkpointer,
    )


def create_agent_runtime(
    settings: Settings | None = None,
    *,
    dynamic_mcp_config: MCPConfig | None = None,
    use_memory_checkpointer: bool = True,
) -> AgentRuntime:
    """Synchronously build the runtime for LangGraph graph imports and CLI use."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            create_agent_runtime_async(
                settings,
                dynamic_mcp_config=dynamic_mcp_config,
                use_memory_checkpointer=use_memory_checkpointer,
            )
        )
    raise RuntimeError(
        "create_agent_runtime() cannot run inside an active event loop; "
        "use create_agent_runtime_async() instead."
    )
