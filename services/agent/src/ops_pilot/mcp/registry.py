"""Small registry object for MCP tools and load metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.config.settings import Settings
from ops_pilot.mcp.loader import load_mcp_tools
from ops_pilot.mcp.status import MCPLoadResult, MCPLoadStatus


@dataclass(frozen=True)
class MCPRegistry:
    tools: tuple[Any, ...] = field(default_factory=tuple)
    status: MCPLoadStatus = field(default_factory=MCPLoadStatus)

    @classmethod
    async def from_settings(cls, settings: Settings) -> MCPRegistry:
        result = await load_mcp_tools(settings)
        if not isinstance(result, MCPLoadResult):
            tools, status = result
            return cls(tools=tuple(tools), status=status)
        return cls(tools=tuple(result.tools), status=result.status)

    @classmethod
    async def from_config(cls, config: MCPConfig, *, config_path: str | None = None) -> MCPRegistry:
        result = await load_mcp_tools(config)
        if isinstance(result, MCPLoadResult):
            return cls(tools=tuple(result.tools), status=result.status)
        tools, status = result
        if config_path is not None:
            status = MCPLoadStatus(config_path=config_path, servers=status.servers)
        return cls(tools=tuple(tools), status=status)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(getattr(tool, "name", repr(tool)) for tool in self.tools)


# Compatibility alias for earlier internal callers.
ToolRegistry = MCPRegistry


async def create_mcp_registry(settings: Settings) -> MCPRegistry:
    return await MCPRegistry.from_settings(settings)
