"""Small registry object for MCP tools and load metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ops_pilot.mcp.loader import load_mcp_tools
from ops_pilot.mcp.spec import MCPServerCatalog
from ops_pilot.mcp.status import MCPLoadStatus


@dataclass(frozen=True)
class MCPRegistry:
    tools: tuple[Any, ...] = field(default_factory=tuple)
    status: MCPLoadStatus = field(default_factory=MCPLoadStatus)
    hitl_tools: tuple[str, ...] = field(default_factory=tuple)
    tool_servers: Mapping[str, str] = field(default_factory=dict)
    retry_tools: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    async def from_catalog(cls, catalog: MCPServerCatalog) -> MCPRegistry:
        result = await load_mcp_tools(catalog)
        return cls(
            tools=tuple(result.tools),
            status=result.status,
            tool_servers=dict(result.tool_servers),
            retry_tools=tuple(result.retry_tools),
        )

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(getattr(tool, "name", repr(tool)) for tool in self.tools)


async def create_mcp_registry(catalog: MCPServerCatalog) -> MCPRegistry:
    return await MCPRegistry.from_catalog(catalog)
