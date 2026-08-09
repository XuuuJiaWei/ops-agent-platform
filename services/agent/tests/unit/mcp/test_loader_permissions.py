from contextlib import asynccontextmanager

import pytest

from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.mcp import loader
from ops_pilot.mcp.loader import _load_single_server, load_mcp_tools


class _DummyTool:
    def __init__(self, name: str) -> None:
        self.name = name


def _config(**server_overrides):
    server = {"transport": "stdio", "command": "npx"}
    server.update(server_overrides)
    return MCPConfig.from_mapping({"mcpServers": {"dyna": server}})


@pytest.fixture
def stub_tools(monkeypatch):
    def _install(names):
        async def _fake_load_single_server(_server):
            return [_DummyTool(name) for name in names]

        monkeypatch.setattr(loader, "_load_single_server", _fake_load_single_server)

    return _install


@pytest.mark.asyncio
async def test_default_allow_keeps_all_tools(stub_tools):
    stub_tools(["get_problems", "restart_service"])

    result = await load_mcp_tools(_config(retry_tools=["get_problems"]))

    assert {tool.name for tool in result.tools} == {"get_problems", "restart_service"}
    assert result.hitl_tools == ()
    assert result.tool_servers == {"get_problems": "dyna", "restart_service": "dyna"}
    assert result.retry_tools == ("get_problems",)


@pytest.mark.asyncio
async def test_allowlist_filters_tools(stub_tools):
    stub_tools(["get_problems", "restart_service", "delete_entity"])

    result = await load_mcp_tools(_config(allow_tools=["get_problems", "restart_service"]))

    assert {tool.name for tool in result.tools} == {"get_problems", "restart_service"}


@pytest.mark.asyncio
async def test_hitl_collected_only_for_surviving_tools(stub_tools):
    stub_tools(["get_problems", "restart_service"])

    result = await load_mcp_tools(_config(allow_tools=["get_problems"], hitl_tools=["restart_service", "get_problems"]))

    # restart_service was filtered out by the allowlist, so it can't be hitl-gated.
    assert {tool.name for tool in result.tools} == {"get_problems"}
    assert result.hitl_tools == ("get_problems",)


@pytest.mark.asyncio
async def test_hitl_collected_for_allowed_tool(stub_tools):
    stub_tools(["get_problems", "restart_service"])

    result = await load_mcp_tools(_config(hitl_tools=["restart_service"]))

    assert result.hitl_tools == ("restart_service",)


@pytest.mark.asyncio
async def test_single_server_tools_reuse_persistent_session(monkeypatch):
    events: list[tuple[str, str, int]] = []
    sessions: list[_FakeSession] = []
    lifecycle_tasks = []

    class FakeClient:
        def __init__(self, connections):
            self.connections = connections

        @asynccontextmanager
        async def session(self, server_name):
            lifecycle_tasks.append(__import__("asyncio").current_task())
            session = _FakeSession()
            sessions.append(session)
            events.append(("enter", server_name, id(session)))
            try:
                yield session
            finally:
                lifecycle_tasks.append(__import__("asyncio").current_task())
                session.closed = True
                events.append(("exit", server_name, id(session)))

    async def fake_load_session_tools(session, *, server_name):
        return [_SessionBackedTool("query", session, server_name)]

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("langchain_mcp_adapters.tools.load_mcp_tools", fake_load_session_tools)

    caller_task = __import__("asyncio").current_task()
    tools, session_owner = await _load_single_server(_config().servers[0])

    assert [tool.name for tool in tools] == ["query"]
    assert len(sessions) == 1
    assert events == [("enter", "dyna", id(sessions[0]))]

    assert await tools[0].ainvoke({"q": "first"}) == "dyna:query:1"
    assert await tools[0].ainvoke({"q": "second"}) == "dyna:query:2"
    assert sessions[0].closed is False
    assert len(sessions) == 1

    await session_owner.aclose()

    assert sessions[0].closed is True
    assert events[-1] == ("exit", "dyna", id(sessions[0]))
    assert lifecycle_tasks[0] is lifecycle_tasks[1]
    assert lifecycle_tasks[0] is not caller_task


class _FakeSession:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    async def call(self, server_name: str, tool_name: str) -> str:
        self.calls += 1
        return f"{server_name}:{tool_name}:{self.calls}"


class _SessionBackedTool:
    def __init__(self, name: str, session: _FakeSession, server_name: str) -> None:
        self.name = name
        self._session = session
        self._server_name = server_name

    async def ainvoke(self, _args):
        return await self._session.call(self._server_name, self.name)
