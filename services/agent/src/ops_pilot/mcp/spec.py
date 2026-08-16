"""Typed MCP declarations owned by a runtime composition.

This module deliberately has no file loader.  A runtime host declares the
servers it needs and passes those declarations to the MCP adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from langchain_mcp_adapters.sessions import Connection
else:
    Connection = dict[str, Any]

SUPPORTED_TRANSPORTS = frozenset({"stdio", "http", "streamable_http", "sse"})


class MCPDeclarationError(ValueError):
    """Raised when a host declares an invalid MCP server."""


@dataclass(frozen=True)
class MCPServerSpec:
    """One MCP server selected by a runtime host."""

    name: str
    transport: str
    required: bool = False
    command: str | None = None
    args: tuple[str, ...] = field(default_factory=tuple)
    cwd: Path | None = None
    url: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    env: Mapping[str, str] = field(default_factory=dict)
    timeout: float | None = None
    read_timeout_seconds: float | None = None
    allow_tools: tuple[str, ...] = field(default_factory=tuple)
    retry_tools: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.transport not in SUPPORTED_TRANSPORTS:
            raise MCPDeclarationError(f"MCP server '{self.name}' uses unsupported transport '{self.transport}'.")
        if self.transport == "stdio" and not self.command:
            raise MCPDeclarationError(f"MCP stdio server '{self.name}' requires a command.")
        if self.transport == "stdio" and self.timeout is not None:
            raise MCPDeclarationError(
                f"MCP stdio server '{self.name}' cannot use timeout; use read_timeout_seconds instead."
            )
        if self.transport in {"http", "streamable_http", "sse"} and not self.url:
            raise MCPDeclarationError(f"MCP {self.transport} server '{self.name}' requires a url.")
        if self.timeout is not None and self.timeout <= 0:
            raise MCPDeclarationError(f"MCP server '{self.name}' timeout must be positive.")
        if self.read_timeout_seconds is not None and self.read_timeout_seconds <= 0:
            raise MCPDeclarationError(f"MCP server '{self.name}' read_timeout_seconds must be positive.")

    def to_client_connection(self) -> Connection:
        transport = "streamable_http" if self.transport == "http" else self.transport
        connection: dict[str, Any] = {"transport": transport}
        if self.command:
            connection["command"] = self.command
        if self.args:
            connection["args"] = list(self.args)
        if self.cwd:
            connection["cwd"] = str(self.cwd.expanduser().resolve())
        if self.url:
            connection["url"] = self.url
        if self.headers:
            connection["headers"] = dict(self.headers)
        if self.timeout is not None and transport in {"streamable_http", "sse"}:
            connection["timeout"] = self.timeout
        if self.env:
            connection["env"] = dict(self.env)
        if self.read_timeout_seconds is not None:
            connection["session_kwargs"] = {
                "read_timeout_seconds": timedelta(seconds=self.read_timeout_seconds),
            }
        return cast("Connection", connection)


@dataclass(frozen=True)
class MCPServerCatalog:
    """The complete MCP capability catalog selected by one runtime host."""

    servers: tuple[MCPServerSpec, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        names = [server.name for server in self.servers]
        if len(names) != len(set(names)):
            raise MCPDeclarationError("MCP server names must be unique within a runtime composition.")
