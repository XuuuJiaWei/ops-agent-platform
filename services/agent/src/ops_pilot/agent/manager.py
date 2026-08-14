"""Mutable holder for the shared agent runtime.

The backend starts with one runtime and can rebuild the graph in-process when
its OpenSandbox lease expires. Existing requests keep the graph they already
cloned; subsequent requests use the latest runtime.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig

from ops_pilot.agent.runtime import AgentRuntime, build_agent_runtime
from ops_pilot.config.settings import Settings


@dataclass(frozen=True)
class RuntimeReloadResult:
    generation: int
    reloaded_at: str
    runtime: AgentRuntime

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "generation": self.generation,
            "reloaded_at": self.reloaded_at,
            "mcp": self.runtime.mcp.status.as_dict(),
            "tools": [getattr(tool, "name", repr(tool)) for tool in self.runtime.tools],
        }


class AgentRuntimeManager:
    """Owns the current runtime and rebuilds it when the sandbox lease lapses."""

    def __init__(
        self,
        *,
        settings: Settings,
        runtime: AgentRuntime | None,
        attach_checkpointer: bool = True,
    ) -> None:
        self.settings = settings
        self._runtime = runtime
        self._attach_checkpointer = attach_checkpointer
        self._generation = 0
        self._reloaded_at = _now_iso()
        self._lock = asyncio.Lock()

    @property
    def current(self) -> AgentRuntime:
        if self._runtime is None:
            raise RuntimeError("Agent runtime is not initialized yet.")
        return self._runtime

    def attach_runtime(self, runtime: AgentRuntime) -> None:
        if self._runtime is not None:
            raise RuntimeError("Agent runtime is already initialized.")
        self._runtime = runtime

    def runtime_proxy(self) -> CurrentRuntimeProxy:
        return CurrentRuntimeProxy(self)

    def graph_proxy(self) -> CurrentGraphProxy:
        return CurrentGraphProxy(self)

    def status(self) -> RuntimeReloadResult:
        return RuntimeReloadResult(
            generation=self._generation,
            reloaded_at=self._reloaded_at,
            runtime=self.current,
        )

    async def ensure_runtime_ready(self) -> RuntimeReloadResult | None:
        """Refresh the runtime when its OpenSandbox lease expired or vanished."""

        sandbox = getattr(self._runtime, "sandbox", None)
        if sandbox is None:
            return None
        if getattr(sandbox, "is_expired", lambda: False)():
            return await self._reload()
        should_renew = getattr(sandbox, "should_renew", lambda: False)
        if not should_renew():
            return None

        async with self._lock:
            sandbox = getattr(self._runtime, "sandbox", None)
            if sandbox is None:
                return None
            if getattr(sandbox, "is_expired", lambda: False)():
                return await self._reload_unlocked()
            should_renew = getattr(sandbox, "should_renew", lambda: False)
            if not should_renew():
                return None
            renew = getattr(sandbox, "renew", None)
            if renew is None:
                return None
            renewed = await asyncio.to_thread(renew)
            if renewed is False:
                return await self._reload_unlocked()
            return None

    async def shutdown(self) -> None:
        async with self._lock:
            if self._runtime is not None:
                await _close_runtime(self._runtime)
                self._runtime = None

    async def _reload(self) -> RuntimeReloadResult:
        async with self._lock:
            return await self._reload_unlocked()

    async def _reload_unlocked(self) -> RuntimeReloadResult:
        previous_runtime = self._runtime
        next_runtime = await build_agent_runtime(
            self.settings,
            attach_checkpointer=self._attach_checkpointer,
        )
        self._runtime = next_runtime
        if previous_runtime is not None:
            await _close_runtime(previous_runtime)
        self._generation += 1
        self._reloaded_at = _now_iso()
        return self.status()


class CurrentRuntimeProxy:
    """Delegates runtime operations to the manager's current runtime."""

    def __init__(self, manager: AgentRuntimeManager) -> None:
        self._manager = manager

    async def ainvoke_text(self, text: str, **kwargs: Any) -> str:
        await self._manager.ensure_runtime_ready()
        return await self._manager.current.ainvoke_text(text, **kwargs)

    def runnable_config(self, **kwargs: Any) -> RunnableConfig:
        return self._manager.current.runnable_config(**kwargs)

    def iterate(self, run_id: str, source: Any, **kwargs: Any) -> Any:
        return self._manager.current.run_controller.iterate(run_id, source, **kwargs)

    async def cancel_run(self, run_id: str, **kwargs: Any) -> bool:
        return await self._manager.current.cancel_run(run_id, **kwargs)


class CurrentGraphProxy:
    """Delegates LangGraph calls to the manager's current graph."""

    def __init__(self, manager: AgentRuntimeManager) -> None:
        self._manager = manager

    @property
    def nodes(self) -> Any:
        return self._manager.current.graph.nodes

    @property
    def context_schema(self) -> Any:
        return getattr(self._manager.current.graph, "context_schema", None)

    def get_input_jsonschema(self, *args: Any, **kwargs: Any) -> Any:
        return self._manager.current.graph.get_input_jsonschema(*args, **kwargs)

    def get_output_jsonschema(self, *args: Any, **kwargs: Any) -> Any:
        return self._manager.current.graph.get_output_jsonschema(*args, **kwargs)

    def config_schema(self, *args: Any, **kwargs: Any) -> Any:
        return self._manager.current.graph.config_schema(*args, **kwargs)

    async def aget_state(self, *args: Any, **kwargs: Any) -> Any:
        await self._manager.ensure_runtime_ready()
        return await self._manager.current.graph.aget_state(*args, **kwargs)

    async def aupdate_state(self, *args: Any, **kwargs: Any) -> Any:
        await self._manager.ensure_runtime_ready()
        return await self._manager.current.graph.aupdate_state(*args, **kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        await self._manager.ensure_runtime_ready()
        return await self._manager.current.graph.ainvoke(*args, **kwargs)

    def astream_events(self, *args: Any, **kwargs: Any) -> Any:
        async def _stream():
            await self._manager.ensure_runtime_ready()
            async for event in self._manager.current.graph.astream_events(*args, **kwargs):
                yield event

        return _stream()

    def aget_state_history(self, *args: Any, **kwargs: Any) -> Any:
        async def _history():
            await self._manager.ensure_runtime_ready()
            async for snapshot in self._manager.current.graph.aget_state_history(*args, **kwargs):
                yield snapshot

        return _history()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _close_runtime(runtime: Any) -> None:
    aclose = getattr(runtime, "aclose", None)
    if aclose is not None:
        await aclose()
        return
    close = getattr(runtime, "close", None)
    if close is not None:
        close()
