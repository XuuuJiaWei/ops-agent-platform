"""Load LangChain tools from deployment-level MCP server config."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, replace
from typing import Any

from ops_pilot.config.mcp_schema import MCPConfig, MCPServerConfig
from ops_pilot.config.settings import Settings
from ops_pilot.mcp.status import MCPLoadResult, MCPLoadStatus, MCPServerLoadStatus

ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")

logger = logging.getLogger(__name__)


class MCPLoadError(RuntimeError):
    """Raised when MCP tool loading cannot continue."""


class RequiredMCPServerError(MCPLoadError):
    """Raised when a required MCP server fails to load."""


class MissingMCPEnvironmentError(MCPLoadError):
    """Raised when an MCP config references an unset environment variable."""


@dataclass
class MCPServerOwner:
    """Own one persistent MCP session entirely inside one asyncio task."""

    _ready: asyncio.Future[list[Any]]
    _stop: asyncio.Event
    _task: asyncio.Task[None] | None = None
    _closed: bool = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._task is None:
            return
        try:
            await self._task
        except BaseException as exc:
            if _is_stdio_shutdown_noise(exc):
                logger.debug("Ignoring MCP stdio shutdown noise: %s", _safe_error(exc))
                return
            raise


async def load_mcp_tools(settings: Settings | MCPConfig) -> MCPLoadResult:
    """Load configured MCP tools and collect per-server status.

    Accepts ``Settings`` (production path, reads the inline ``settings.mcp``
    config) or an ``MCPConfig`` directly (dynamic developer-mode servers).
    """

    if isinstance(settings, MCPConfig):
        return await _load_from_config(settings, config_path=None)

    if not settings.mcp.servers:
        return MCPLoadResult(tools=[], status=MCPLoadStatus(config_path=None, servers=()))

    return await _load_from_config(settings.mcp, config_path="config.yaml")


async def _load_from_config(config: MCPConfig, *, config_path: str | None) -> MCPLoadResult:
    tools: list[Any] = []
    statuses: list[MCPServerLoadStatus] = []
    hitl_tools: list[str] = []
    retry_tools: list[str] = []
    tool_servers: dict[str, str] = {}
    session_managers: list[MCPServerOwner] = []

    async def load(server: MCPServerConfig) -> Any:
        return await _load_single_server_with_timeout(_expand_server_env(server))

    results = await asyncio.gather(*(load(server) for server in config.servers), return_exceptions=True)
    all_owners = [
        owner
        for result in results
        if not isinstance(result, BaseException)
        for _, owner in [_unpack_server_load_result(result)]
        if owner is not None
    ]

    for server, result in zip(config.servers, results, strict=True):
        if isinstance(result, BaseException):
            exc = result
            status = MCPServerLoadStatus(
                name=server.name,
                required=server.required,
                transport=server.transport,
                ok=False,
                error=_safe_error(exc),
            )
            statuses.append(status)
            if server.required:
                await _close_owners(all_owners)
                raise RequiredMCPServerError(
                    f"Required MCP server '{server.name}' failed to load: {status.error}"
                ) from exc
            logger.warning("Optional MCP server '%s' failed to load: %s", server.name, status.error)
            continue

        server_tools, owner = _unpack_server_load_result(result)
        kept_tools = _apply_allowlist(server, server_tools)
        tools.extend(kept_tools)
        hitl_tools.extend(_collect_hitl_tools(server, kept_tools))
        kept_names = {_tool_name(tool) for tool in kept_tools}
        tool_servers.update({name: server.name for name in kept_names})
        retry_tools.extend(name for name in server.retry_tools if name in kept_names)
        if owner is not None:
            if kept_tools:
                session_managers.append(owner)
            else:
                await owner.aclose()
        statuses.append(
            MCPServerLoadStatus(
                name=server.name,
                required=server.required,
                transport=server.transport,
                ok=True,
                tool_count=len(kept_tools),
            )
        )
        logger.info("MCP server '%s' loaded %d tools", server.name, len(kept_tools))

    status = MCPLoadStatus(config_path=config_path, servers=tuple(statuses))
    logger.info(
        "MCP runtime loaded %d/%d servers with %d tools",
        sum(server.ok for server in statuses),
        len(statuses),
        status.tool_count,
    )
    return MCPLoadResult(
        tools=tools,
        status=status,
        hitl_tools=tuple(dict.fromkeys(hitl_tools)),
        session_managers=tuple(session_managers),
        tool_servers=tool_servers,
        retry_tools=tuple(dict.fromkeys(retry_tools)),
    )


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", ""))


def _apply_allowlist(server: MCPServerConfig, tools: list[Any]) -> list[Any]:
    """Keep only allowlisted tools. Empty/omitted ``allow_tools`` allows all."""

    if not server.allow_tools:
        return tools
    allowed = set(server.allow_tools)
    kept = [tool for tool in tools if _tool_name(tool) in allowed]
    unmatched = allowed - {_tool_name(tool) for tool in tools}
    if unmatched:
        logger.warning(
            "MCP server '%s' allow_tools entries matched no loaded tool: %s",
            server.name,
            ", ".join(sorted(unmatched)),
        )
    return kept


def _collect_hitl_tools(server: MCPServerConfig, kept_tools: list[Any]) -> list[str]:
    """Return hitl tool names that survived the allowlist; warn on non-matches."""

    if not server.hitl_tools:
        return []
    kept_names = {_tool_name(tool) for tool in kept_tools}
    hitl = [name for name in server.hitl_tools if name in kept_names]
    unmatched = set(server.hitl_tools) - kept_names
    if unmatched:
        logger.warning(
            "MCP server '%s' hitl_tools entries matched no loaded/allowed tool: %s",
            server.name,
            ", ".join(sorted(unmatched)),
        )
    return hitl


async def _load_single_server(server: MCPServerConfig) -> tuple[list[Any], MCPServerOwner]:
    loop = asyncio.get_running_loop()
    owner = MCPServerOwner(
        _ready=loop.create_future(),
        _stop=asyncio.Event(),
    )
    owner._task = asyncio.create_task(_run_server_owner(owner, server), name=f"mcp-owner:{server.name}")
    try:
        tools = await asyncio.shield(owner._ready)
    except BaseException:
        owner._closed = True
        owner._task.cancel()
        await asyncio.gather(owner._task, return_exceptions=True)
        raise
    return tools, owner


async def _run_server_owner(owner: MCPServerOwner, server: MCPServerConfig) -> None:
    stack = AsyncExitStack()
    try:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            from langchain_mcp_adapters.tools import load_mcp_tools as load_session_tools
        except ImportError as exc:
            raise MCPLoadError("langchain-mcp-adapters is not installed. Run 'uv sync' in services/agent.") from exc

        client = MultiServerMCPClient({server.name: server.to_client_connection()})
        session = await stack.enter_async_context(client.session(server.name))
        tools = list(await load_session_tools(session, server_name=server.name))
        if not owner._ready.done():
            owner._ready.set_result(tools)
        await owner._stop.wait()
    except BaseException as exc:
        if not owner._ready.done():
            owner._ready.set_exception(exc)
            return
        raise
    finally:
        await stack.aclose()


async def _load_single_server_with_timeout(server: MCPServerConfig) -> tuple[list[Any], MCPServerOwner]:
    if server.timeout is None:
        return await _load_single_server(server)
    try:
        return await asyncio.wait_for(_load_single_server(server), timeout=server.timeout)
    except TimeoutError as exc:
        timeout = f"{server.timeout:g}"
        raise MCPLoadError(f"MCP server '{server.name}' timed out after {timeout}s while loading tools.") from exc


def _unpack_server_load_result(loaded: Any) -> tuple[list[Any], MCPServerOwner | None]:
    """Accept old test doubles while production returns tools plus session owner."""

    if isinstance(loaded, tuple) and len(loaded) == 2:
        tools, owner = loaded
        return list(tools), owner
    return list(loaded), None


async def _close_owners(owners: list[MCPServerOwner]) -> None:
    seen: set[int] = set()
    for owner in reversed(owners):
        if id(owner) in seen:
            continue
        seen.add(id(owner))
        await owner.aclose()


def _expand_server_env(server: MCPServerConfig) -> MCPServerConfig:
    return replace(server, headers=_expand_mapping(server.headers), env=_expand_mapping(server.env))


def _expand_mapping(values: Mapping[str, str]) -> dict[str, str]:
    return {key: _expand_env_value(value) for key, value in values.items()}


def _expand_env_value(value: str) -> str:
    missing: set[str] = set()

    def replace_match(match: re.Match[str]) -> str:
        name = match.group(1)
        resolved = os.environ.get(name)
        if resolved in (None, ""):
            missing.add(name)
            return match.group(0)
        return resolved

    expanded = ENV_PATTERN.sub(replace_match, value)
    if missing:
        variables = ", ".join(sorted(missing))
        raise MissingMCPEnvironmentError(f"Missing environment variable(s) referenced by MCP config: {variables}")
    return expanded


def _safe_error(exc: BaseException) -> str:
    text = _error_text(exc)
    for key, value in os.environ.items():
        if _looks_secret(key) and value:
            text = text.replace(value, "[redacted]")
    return text


def _is_stdio_shutdown_noise(exc: BaseException) -> bool:
    text = _error_text(exc)
    return any(
        marker in text
        for marker in (
            "Received SIGTERM, terminating child process",
            "Child process terminated by signal: SIGTERM",
            "BrokenResourceError",
        )
    )


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        parts = [_error_text(child) for child in exc.exceptions]
        joined = "; ".join(part for part in parts if part)
        return joined or (str(exc) or exc.__class__.__name__)
    return str(exc) or exc.__class__.__name__


def _looks_secret(key: str) -> bool:
    key_upper = key.upper()
    return any(marker in key_upper for marker in ("TOKEN", "SECRET", "PASSWORD", "KEY"))
