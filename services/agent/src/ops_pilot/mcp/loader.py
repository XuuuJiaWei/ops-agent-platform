"""Load LangChain tools with the official MCP adapter."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient

from ops_pilot.errors import safe_exception_summary
from ops_pilot.mcp.spec import MCPServerCatalog, MCPServerSpec
from ops_pilot.mcp.status import MCPLoadResult, MCPLoadStatus, MCPServerLoadStatus

logger = logging.getLogger(__name__)
MCP_LOAD_MAX_ATTEMPTS = 3
MCP_LOAD_RETRY_DELAY_SECONDS = 0.5
MCP_CONNECT_MAX_RETRIES = 2


class MCPLoadError(RuntimeError):
    """Raised when configured MCP tools cannot be loaded."""


class RequiredMCPServerError(MCPLoadError):
    """Raised when a required MCP server fails initialization."""


async def load_mcp_tools(catalog: MCPServerCatalog) -> MCPLoadResult:
    """Initialize configured servers and return loop-neutral LangChain tools.

    ``MultiServerMCPClient.get_tools`` owns the protocol lifecycle. The tools it
    returns create a fresh MCP session for each call, so the compiled agent can
    be invoked from Langfuse worker event loops without a local reconnect layer.
    """

    if not catalog.servers:
        return MCPLoadResult(tools=[], status=MCPLoadStatus())

    connections: dict[str, Any] = {}
    for server in catalog.servers:
        connection = dict(server.to_client_connection())
        if connection["transport"] == "streamable_http":
            connection["httpx_client_factory"] = _create_http_client
        connections[server.name] = connection
    client = MultiServerMCPClient(connections, handle_tool_errors=True)

    async def load(server: MCPServerSpec) -> list[Any]:
        for attempt in range(1, MCP_LOAD_MAX_ATTEMPTS + 1):
            try:
                return list(await client.get_tools(server_name=server.name))
            except Exception as exc:
                if attempt == MCP_LOAD_MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "MCP server '%s' tool discovery failed (attempt %d/%d): %s",
                    server.name,
                    attempt,
                    MCP_LOAD_MAX_ATTEMPTS,
                    safe_exception_summary(exc),
                )
                await asyncio.sleep(MCP_LOAD_RETRY_DELAY_SECONDS * attempt)
        raise AssertionError("unreachable")

    loaded = await asyncio.gather(*(load(server) for server in catalog.servers), return_exceptions=True)
    tools: list[Any] = []
    statuses: list[MCPServerLoadStatus] = []
    retry_tools: list[str] = []
    tool_servers: dict[str, str] = {}

    for server, result in zip(catalog.servers, loaded, strict=True):
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
        status=MCPLoadStatus(servers=tuple(statuses)),
        tool_servers=tool_servers,
        retry_tools=tuple(dict.fromkeys(retry_tools)),
    )


def _allowed_tools(server: MCPServerSpec, tools: list[Any]) -> list[Any]:
    if not server.allow_tools:
        return tools
    allowed = set(server.allow_tools)
    return [tool for tool in tools if _tool_name(tool) in allowed]


def _warn_unknown_policy_tools(server: MCPServerSpec, loaded_names: set[str]) -> None:
    configured = set(server.allow_tools) | set(server.retry_tools)
    unknown = configured - loaded_names
    if unknown:
        logger.warning(
            "MCP server '%s' policy entries matched no loaded tool: %s",
            server.name,
            ", ".join(sorted(unknown)),
        )


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", ""))


def _create_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=True,
        transport=httpx.AsyncHTTPTransport(retries=MCP_CONNECT_MAX_RETRIES),
    )
