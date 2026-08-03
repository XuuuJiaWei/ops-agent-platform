"""Resolve local MCP tunnel profiles into executable process specs."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path

from ops_pilot.config.mcp_schema import MCPConfig, MCPConfigError, MCPServerConfig


@dataclass(frozen=True)
class MCPProcessSpec:
    command: str
    env: dict[str, str] = field(default_factory=dict)


def resolve_tunnel_mcp_spec(
    *,
    mcp_command: str | None,
    mcp_config: str | None,
    mcp_server: str | None,
) -> MCPProcessSpec:
    if bool(mcp_command) == bool(mcp_config):
        raise ValueError("Pass exactly one of mcp_command or mcp_config.")
    if mcp_command:
        return MCPProcessSpec(command=mcp_command, env={})
    assert mcp_config is not None
    try:
        config = MCPConfig.load(Path(mcp_config).expanduser())
    except MCPConfigError as exc:
        raise ValueError(str(exc)) from exc
    server = select_mcp_server(config, mcp_server)
    if server.transport != "stdio":
        raise ValueError(
            f"Tunnel local MCP config must select a stdio server; '{server.name}' uses {server.transport}."
        )
    command = [server.command or "", *server.args]
    return MCPProcessSpec(command=shlex.join(command), env=dict(server.env))


def select_mcp_server(config: MCPConfig, name: str | None) -> MCPServerConfig:
    if name:
        for server in config.servers:
            if server.name == name:
                return server
        raise ValueError(f"MCP config does not contain server '{name}'.")
    if len(config.servers) == 1:
        return config.servers[0]
    names = ", ".join(server.name for server in config.servers) or "none"
    raise ValueError(f"MCP config has multiple servers ({names}); pass mcp_server.")
