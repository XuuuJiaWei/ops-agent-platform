"""Resilient persistent MCP session ownership behind stable LangChain tools."""

from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg

from ops_pilot.config.mcp_schema import MCPServerConfig
from ops_pilot.mcp.errors import is_mcp_session_disconnect, is_mcp_shutdown_noise

logger = logging.getLogger(__name__)


@dataclass
class _SessionGeneration:
    number: int
    stack: AsyncExitStack
    tools: dict[str, Any]
    accepting: bool = True
    active_calls: int = 0
    idle: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.idle.set()


@dataclass(frozen=True)
class _Refresh:
    expected_generation: int | None
    completed: asyncio.Future[None]


@dataclass(frozen=True)
class _Close:
    completed: asyncio.Future[None]


class PersistentMCPServer:
    """Own one server's session generations in a single lifecycle task.

    Callers receive stable LangChain tools. Each proxy dispatches to the current
    session generation, so replacing a dead session does not require rebuilding
    the agent graph. Tool calls remain concurrent; reconnect and teardown are
    serialized in the task that created the AnyIO/MCP context managers.
    """

    def __init__(self, server: MCPServerConfig) -> None:
        loop = asyncio.get_running_loop()
        self._server = server
        self._loop = loop
        self._ready: asyncio.Future[list[Any]] = loop.create_future()
        self._commands: asyncio.Queue[_Refresh | _Close] = asyncio.Queue()
        self._state_lock = asyncio.Lock()
        self._generation: _SessionGeneration | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    @classmethod
    async def start(cls, server: MCPServerConfig) -> tuple[list[Any], PersistentMCPServer]:
        owner = cls(server)
        owner._task = asyncio.create_task(owner._run(), name=f"mcp-owner:{server.name}")
        try:
            tools = await asyncio.shield(owner._ready)
        except BaseException:
            owner._closed = True
            owner._task.cancel()
            await asyncio.gather(owner._task, return_exceptions=True)
            raise
        return tools, owner

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        task = self._task
        if task is None:
            return
        if not task.done():
            completed: asyncio.Future[None] = self._loop.create_future()
            await self._commands.put(_Close(completed=completed))
            done, _ = await asyncio.wait((completed, task), return_when=asyncio.FIRST_COMPLETED)
            if completed in done:
                await completed
        try:
            await task
        except BaseException as exc:
            if not is_mcp_shutdown_noise(exc):
                raise
            logger.debug("Ignoring MCP shutdown noise for %s: %s", self._server.name, exc)

    async def _run(self) -> None:
        try:
            initial = await self._open_generation(1)
            async with self._state_lock:
                self._generation = initial
            self._ready.set_result([self._make_proxy(tool) for tool in initial.tools.values()])

            while True:
                command = await self._commands.get()
                if isinstance(command, _Close):
                    try:
                        await self._retire_current_generation()
                    except BaseException as exc:
                        if not command.completed.done():
                            command.completed.set_exception(exc)
                        raise
                    else:
                        if not command.completed.done():
                            command.completed.set_result(None)
                    return
                await self._handle_refresh(command)
        except BaseException as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
                return
            raise
        finally:
            await self._retire_current_generation()

    async def _handle_refresh(self, command: _Refresh) -> None:
        try:
            async with self._state_lock:
                current = self._generation
                should_refresh = (
                    current is None
                    if command.expected_generation is None
                    else current is not None and current.number == command.expected_generation
                )
                if should_refresh and current is not None:
                    current.accepting = False
            if should_refresh:
                previous_number = current.number if current is not None else 0
                await self._retire_current_generation()
                replacement = await self._open_generation(previous_number + 1)
                async with self._state_lock:
                    self._generation = replacement
            if not command.completed.done():
                command.completed.set_result(None)
        except Exception as exc:
            if not command.completed.done():
                command.completed.set_exception(exc)

    async def _open_generation(self, number: int) -> _SessionGeneration:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            from langchain_mcp_adapters.tools import load_mcp_tools as load_session_tools
        except ImportError as exc:
            raise RuntimeError("langchain-mcp-adapters is not installed. Run 'uv sync' in services/agent.") from exc

        stack = AsyncExitStack()
        try:
            client = MultiServerMCPClient({self._server.name: self._server.to_client_connection()})
            session = await stack.enter_async_context(client.session(self._server.name))
            loaded = list(await load_session_tools(session, server_name=self._server.name))
            tools = {str(tool.name): tool for tool in loaded}
            if len(tools) != len(loaded):
                raise RuntimeError(f"MCP server '{self._server.name}' exposed duplicate tool names.")
            return _SessionGeneration(number=number, stack=stack, tools=tools)
        except BaseException:
            await stack.aclose()
            raise

    async def _retire_current_generation(self) -> None:
        async with self._state_lock:
            generation = self._generation
            if generation is None:
                return
            generation.accepting = False
            self._generation = None
        await generation.idle.wait()
        await generation.stack.aclose()

    def _make_proxy(self, tool: Any) -> Any:
        coroutine = getattr(tool, "coroutine", None)
        model_copy = getattr(tool, "model_copy", None)
        if not callable(coroutine) or not callable(model_copy):
            raise TypeError(f"MCP tool {getattr(tool, 'name', tool)!r} is not an async LangChain StructuredTool.")
        tool_name = str(tool.name)

        async def call_current(
            runtime: Annotated[object | None, InjectedToolArg()] = None,
            **arguments: dict[str, Any],
        ) -> Any:
            return await self._invoke(tool_name, runtime=runtime, arguments=arguments)

        return model_copy(update={"coroutine": call_current})

    async def _invoke(self, tool_name: str, *, runtime: object | None, arguments: dict[str, Any]) -> Any:
        generation = await self._acquire_generation()
        disconnected: BaseException | None = None
        try:
            tool = generation.tools.get(tool_name)
            if tool is None:
                raise RuntimeError(
                    f"MCP tool '{tool_name}' disappeared after reconnecting server '{self._server.name}'. "
                    "Restart the runtime to refresh the tool catalog."
                )
            coroutine = getattr(tool, "coroutine", None)
            if not callable(coroutine):
                raise TypeError(f"MCP tool '{tool_name}' no longer has an async coroutine.")
            call_arguments = dict(arguments)
            if "runtime" in inspect.signature(coroutine).parameters:
                call_arguments["runtime"] = runtime
            result = coroutine(**call_arguments)
            if not inspect.isawaitable(result):
                raise TypeError(f"MCP tool '{tool_name}' coroutine did not return an awaitable.")
            return await result
        except BaseException as exc:
            if not is_mcp_session_disconnect(exc):
                raise
            disconnected = exc
        finally:
            await self._release_generation(generation)

        assert disconnected is not None
        try:
            await self._request_refresh(generation.number)
        except BaseException as reconnect_error:
            logger.warning(
                "MCP server '%s' session %d terminated and reconnect failed: %s",
                self._server.name,
                generation.number,
                reconnect_error,
            )
        raise disconnected

    async def _acquire_generation(self) -> _SessionGeneration:
        while True:
            async with self._state_lock:
                if self._closed:
                    raise RuntimeError(f"MCP server '{self._server.name}' is closed.")
                generation = self._generation
                if generation is not None and generation.accepting:
                    generation.active_calls += 1
                    generation.idle.clear()
                    return generation
            await self._request_refresh(None)

    async def _release_generation(self, generation: _SessionGeneration) -> None:
        async with self._state_lock:
            generation.active_calls -= 1
            if generation.active_calls == 0:
                generation.idle.set()

    async def _request_refresh(self, expected_generation: int | None) -> None:
        if self._closed:
            raise RuntimeError(f"MCP server '{self._server.name}' is closed.")
        completed: asyncio.Future[None] = self._loop.create_future()
        await self._commands.put(_Refresh(expected_generation=expected_generation, completed=completed))
        await completed
