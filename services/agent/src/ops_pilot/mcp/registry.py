"""Small registry object for MCP tools and load metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.config.settings import Settings
from ops_pilot.mcp.loader import load_mcp_tools
from ops_pilot.mcp.status import MCPLoadStatus


@dataclass(frozen=True)
class MCPRegistry:
    tools: tuple[Any, ...] = field(default_factory=tuple)
    status: MCPLoadStatus = field(default_factory=MCPLoadStatus)
    hitl_tools: tuple[str, ...] = field(default_factory=tuple)
    session_managers: tuple[Any, ...] = field(default_factory=tuple)
    tool_servers: Mapping[str, str] = field(default_factory=dict)
    retry_tools: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    async def from_settings(cls, settings: Settings) -> MCPRegistry:
        result = await load_mcp_tools(settings)
        return cls(
            tools=tuple(result.tools),
            status=result.status,
            hitl_tools=tuple(result.hitl_tools),
            session_managers=tuple(result.session_managers),
            tool_servers=dict(result.tool_servers),
            retry_tools=tuple(result.retry_tools),
        )

    @classmethod
    async def from_config(cls, config: MCPConfig, *, config_path: str | None = None) -> MCPRegistry:
        result = await load_mcp_tools(config)
        status = result.status
        if config_path is not None:
            status = MCPLoadStatus(config_path=config_path, servers=status.servers)
        return cls(
            tools=tuple(result.tools),
            status=status,
            hitl_tools=tuple(result.hitl_tools),
            session_managers=tuple(result.session_managers),
            tool_servers=dict(result.tool_servers),
            retry_tools=tuple(result.retry_tools),
        )

    async def aclose(self) -> None:
        for manager in reversed(self.session_managers):
            aclose = getattr(manager, "aclose", None)
            if aclose is not None:
                await aclose()

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(getattr(tool, "name", repr(tool)) for tool in self.tools)


async def create_mcp_registry(settings: Settings) -> MCPRegistry:
    return await MCPRegistry.from_settings(settings)
