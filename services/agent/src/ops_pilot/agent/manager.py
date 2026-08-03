"""Mutable holder for the shared agent runtime.

The backend starts with one runtime, then developer-mode MCP changes can rebuild
the graph in-process. Existing requests keep the graph they already cloned;
subsequent requests use the latest runtime.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ops_pilot.agent.runtime import AgentRuntime, build_agent_runtime
from ops_pilot.config.mcp_schema import MCPConfig, MCPServerConfig
from ops_pilot.config.settings import Settings
from ops_pilot.mcp.status import MCPLoadStatus


@dataclass(frozen=True)
class RuntimeReloadResult:
    generation: int
    reloaded_at: str
    runtime: AgentRuntime
    dynamic_mcp: MCPLoadStatus

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "generation": self.generation,
            "reloaded_at": self.reloaded_at,
            "mcp": self.runtime.mcp.status.as_dict(),
            "dynamic_mcp": self.dynamic_mcp.as_dict(),
            "tools": [getattr(tool, "name", repr(tool)) for tool in self.runtime.tools],
        }


class AgentRuntimeManager:
    """Owns the current runtime and rebuilds it after dynamic config changes."""

    def __init__(
        self,
        *,
        settings: Settings,
        runtime: AgentRuntime,
        use_memory_checkpointer: bool = True,
    ) -> None:
        self.settings = settings
        self._runtime = runtime
        self._use_memory_checkpointer = use_memory_checkpointer
        self._dynamic_mcp_servers: dict[str, MCPServerConfig] = {}
        self._generation = 0
        self._reloaded_at = _now_iso()
        self._lock = asyncio.Lock()

    @property
    def current(self) -> AgentRuntime:
        return self._runtime

    def runtime_proxy(self) -> CurrentRuntimeProxy:
        return CurrentRuntimeProxy(self)

    def graph_proxy(self) -> CurrentGraphProxy:
        return CurrentGraphProxy(self)

    def status(self) -> RuntimeReloadResult:
        return RuntimeReloadResult(
            generation=self._generation,
            reloaded_at=self._reloaded_at,
            runtime=self._runtime,
            dynamic_mcp=self._dynamic_mcp_status(self._runtime),
        )

    async def apply_mcp_server(self, server: MCPServerConfig) -> RuntimeReloadResult:
        next_servers = dict(self._dynamic_mcp_servers)
        next_servers[server.name] = server
        return await self._reload(next_servers)

    async def remove_mcp_server(self, name: str) -> RuntimeReloadResult:
        next_servers = dict(self._dynamic_mcp_servers)
        next_servers.pop(name, None)
        return await self._reload(next_servers)

    async def reload(self) -> RuntimeReloadResult:
        return await self._reload(dict(self._dynamic_mcp_servers))

    async def _reload(self, dynamic_servers: dict[str, MCPServerConfig]) -> RuntimeReloadResult:
        async with self._lock:
            dynamic_config = MCPConfig(servers=tuple(dynamic_servers.values()))
            next_runtime = await build_agent_runtime(
                self.settings,
                dynamic_mcp_config=dynamic_config,
                use_memory_checkpointer=self._use_memory_checkpointer,
            )
            self._runtime = next_runtime
            self._dynamic_mcp_servers = dynamic_servers
            self._generation += 1
            self._reloaded_at = _now_iso()
            return self.status()

    def _dynamic_mcp_status(self, runtime: AgentRuntime) -> MCPLoadStatus:
        names = set(self._dynamic_mcp_servers)
        return MCPLoadStatus(
            config_path="dynamic" if names else None,
            servers=tuple(server for server in runtime.mcp.status.servers if server.name in names),
        )


class CurrentRuntimeProxy:
    """Delegates runtime operations to the manager's current runtime."""

    def __init__(self, manager: AgentRuntimeManager) -> None:
        self._manager = manager

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager.current, name)

    async def ainvoke_text(self, text: str, **kwargs: Any) -> str:
        return await self._manager.current.ainvoke_text(text, **kwargs)

    def runnable_config(self, **kwargs: Any) -> dict[str, Any]:
        return self._manager.current.runnable_config(**kwargs)


class CurrentGraphProxy:
    """Delegates LangGraph calls to the manager's current graph."""

    def __init__(self, manager: AgentRuntimeManager) -> None:
        self._manager = manager

    @property
    def nodes(self) -> Any:
        return self._manager.current.graph.nodes

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager.current.graph, name)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
