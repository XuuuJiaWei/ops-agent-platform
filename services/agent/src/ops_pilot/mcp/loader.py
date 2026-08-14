"""Load LangChain tools with the official MCP adapter."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from ops_pilot.config.mcp_schema import MCPConfig, MCPServerConfig
from ops_pilot.config.settings import Settings
from ops_pilot.errors import safe_exception_summary
from ops_pilot.mcp.status import MCPLoadResult, MCPLoadStatus, MCPServerLoadStatus

logger = logging.getLogger(__name__)


class MCPLoadError(RuntimeError):
    """Raised when configured MCP tools cannot be loaded."""


class RequiredMCPServerError(MCPLoadError):
    """Raised when a required MCP server fails initialization."""


async def load_mcp_tools(settings: Settings | MCPConfig) -> MCPLoadResult:
    """Initialize configured servers and return loop-neutral LangChain tools.

    ``MultiServerMCPClient.get_tools`` owns the protocol lifecycle. The tools it
    returns create a fresh MCP session for each call, so the compiled agent can
    be invoked from Langfuse worker event loops without a local reconnect layer.
    """

    config = settings if isinstance(settings, MCPConfig) else settings.mcp
    config_path = None if isinstance(settings, MCPConfig) else "config.yaml"
    if not config.servers:
        return MCPLoadResult(tools=[], status=MCPLoadStatus(config_path=config_path))

    client = MultiServerMCPClient(
        {server.name: server.to_client_connection() for server in config.servers},
        handle_tool_errors=True,
    )

    async def load(server: MCPServerConfig) -> list[Any]:
        return list(await client.get_tools(server_name=server.name))

    loaded = await asyncio.gather(*(load(server) for server in config.servers), return_exceptions=True)
    tools: list[Any] = []
    statuses: list[MCPServerLoadStatus] = []
    hitl_tools: list[str] = []
    retry_tools: list[str] = []
    tool_servers: dict[str, str] = {}

    for server, result in zip(config.servers, loaded, strict=True):
        if isinstance(result, BaseException):
            error = safe_exception_summary(result, limit=2000)
            statuses.append(
                MCPServerLoadStatus(
                    name=server.name,
                    required=server.required,
                    transport=server.transport,
                    ok=False,
                    error=error,
                )
            )
            if server.required:
                raise RequiredMCPServerError(f"Required MCP server '{server.name}' failed to load: {error}") from result
            logger.warning("Optional MCP server '%s' failed to load: %s", server.name, error)
            continue

        server_tools = _allowed_tools(server, result)
        names = {_tool_name(tool) for tool in server_tools}
        _warn_unknown_policy_tools(server, names)
        tools.extend(server_tools)
        hitl_tools.extend(name for name in server.hitl_tools if name in names)
        retry_tools.extend(name for name in server.retry_tools if name in names)
        tool_servers.update({name: server.name for name in names})
        statuses.append(
            MCPServerLoadStatus(
                name=server.name,
                required=server.required,
                transport=server.transport,
                ok=True,
                tool_count=len(server_tools),
            )
        )

    return MCPLoadResult(
        tools=tools,
        status=MCPLoadStatus(config_path=config_path, servers=tuple(statuses)),
        hitl_tools=tuple(dict.fromkeys(hitl_tools)),
        tool_servers=tool_servers,
        retry_tools=tuple(dict.fromkeys(retry_tools)),
    )


def _allowed_tools(server: MCPServerConfig, tools: list[Any]) -> list[Any]:
    if not server.allow_tools:
        return tools
    allowed = set(server.allow_tools)
    return [tool for tool in tools if _tool_name(tool) in allowed]


def _warn_unknown_policy_tools(server: MCPServerConfig, loaded_names: set[str]) -> None:
    configured = set(server.allow_tools) | set(server.hitl_tools) | set(server.retry_tools)
    unknown = configured - loaded_names
    if unknown:
        logger.warning(
            "MCP server '%s' policy entries matched no loaded tool: %s",
            server.name,
            ", ".join(sorted(unknown)),
        )


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", ""))
