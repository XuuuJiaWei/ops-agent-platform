"""Load LangChain tools from deployment-level MCP server config."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ops_pilot.config.mcp_schema import MCPConfig, MCPConfigError, MCPServerConfig
from ops_pilot.config.paths import display_path
from ops_pilot.config.settings import Settings
from ops_pilot.mcp.status import MCPLoadResult, MCPLoadStatus, MCPServerLoadStatus

ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


class MCPLoadError(RuntimeError):
    """Raised when MCP tool loading cannot continue."""


class RequiredMCPServerError(MCPLoadError):
    """Raised when a required MCP server fails to load."""


async def load_mcp_tools(settings: Settings | MCPConfig) -> MCPLoadResult:
    """Load configured MCP tools and collect per-server status.

    Accepts ``Settings`` (production path, reads ``mcp_config_path``) or an
    ``MCPConfig`` directly (dynamic developer-mode servers).
    """

    if isinstance(settings, MCPConfig):
        return await _load_from_config(settings, config_path=None)

    if settings.mcp_config_path is None:
        return MCPLoadResult(tools=[], status=MCPLoadStatus(config_path=None, servers=()))

    try:
        config = MCPConfig.load(settings.mcp_config_path)
    except MCPConfigError as exc:
        raise MCPLoadError(str(exc)) from exc
    return await _load_from_config(config, config_path=display_path(settings.mcp_config_path))


async def _load_from_config(config: MCPConfig, *, config_path: str | None) -> MCPLoadResult:
    tools: list[Any] = []
    statuses: list[MCPServerLoadStatus] = []

    for server in config.servers:
        expanded = _expand_server_env(server)
        try:
            server_tools = await _load_single_server(expanded)
        except Exception as exc:  # noqa: BLE001 - convert adapter errors to startup status.
            status = MCPServerLoadStatus(
                name=server.name,
                required=server.required,
                transport=server.transport,
                ok=False,
                error=_safe_error(exc),
            )
            statuses.append(status)
            if server.required:
                raise RequiredMCPServerError(
                    f"Required MCP server '{server.name}' failed to load: {status.error}"
                ) from exc
            continue

        tools.extend(server_tools)
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
    )


async def _load_single_server(server: MCPServerConfig) -> list[Any]:
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as exc:
        raise MCPLoadError("langchain-mcp-adapters is not installed. Run 'uv sync' in services/agent.") from exc

    client = MultiServerMCPClient({server.name: server.to_client_connection()})
    return list(await client.get_tools(server_name=server.name))


def _expand_server_env(server: MCPServerConfig) -> MCPServerConfig:
    return replace(server, headers=_expand_mapping(server.headers), env=_expand_mapping(server.env))


def _expand_mapping(values: Mapping[str, str]) -> dict[str, str]:
    return {key: _expand_env_value(value) for key, value in values.items()}


def _expand_env_value(value: str) -> str:
    def replace_match(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return ENV_PATTERN.sub(replace_match, value)


def _safe_error(exc: BaseException) -> str:
    text = _error_text(exc)
    for key, value in os.environ.items():
        if _looks_secret(key) and value:
            text = text.replace(value, "[redacted]")
    return text


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        parts = [_error_text(child) for child in exc.exceptions]
        joined = "; ".join(part for part in parts if part)
        return joined or (str(exc) or exc.__class__.__name__)
    return str(exc) or exc.__class__.__name__


def _looks_secret(key: str) -> bool:
    key_upper = key.upper()
    return any(marker in key_upper for marker in ("TOKEN", "SECRET", "PASSWORD", "KEY"))
