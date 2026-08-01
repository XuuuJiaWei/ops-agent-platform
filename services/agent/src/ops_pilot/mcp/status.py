"""Status objects for MCP server loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MCPServerLoadStatus:
    name: str
    required: bool
    transport: str
    ok: bool
    tool_count: int = 0
    error: str | None = None

    @property
    def warning(self) -> str | None:
        if self.ok or self.required:
            return None
        return self.error or f"Optional MCP server '{self.name}' failed to load."


@dataclass(frozen=True)
class MCPLoadStatus:
    config_path: str | None = None
    servers: tuple[MCPServerLoadStatus, ...] = field(default_factory=tuple)

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(status.warning for status in self.servers if status.warning)

    @property
    def tool_count(self) -> int:
        return sum(status.tool_count for status in self.servers)

    @property
    def has_required_failure(self) -> bool:
        return any(server.required and not server.ok for server in self.servers)

    def as_dict(self) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "tool_count": self.tool_count,
            "warnings": list(self.warnings),
            "has_required_failure": self.has_required_failure,
            "servers": [
                {
                    "name": server.name,
                    "required": server.required,
                    "transport": server.transport,
                    "ok": server.ok,
                    "tool_count": server.tool_count,
                    "error": server.error,
                }
                for server in self.servers
            ],
        }


@dataclass(frozen=True)
class MCPLoadResult:
    tools: list[Any]
    status: MCPLoadStatus


# Compatibility aliases for earlier internal tests/callers.
MCPServerStatus = MCPServerLoadStatus
MCPStatus = MCPLoadStatus
