import pytest

from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.mcp import loader
from ops_pilot.mcp.loader import load_mcp_tools


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

    result = await load_mcp_tools(_config())

    assert {tool.name for tool in result.tools} == {"get_problems", "restart_service"}
    assert result.hitl_tools == ()


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
