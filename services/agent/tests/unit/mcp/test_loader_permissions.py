import pytest

from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.mcp import loader
from ops_pilot.mcp.loader import load_mcp_tools


class _DummyTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeClient:
    names: list[str] = []

    def __init__(self, connections, **kwargs):
        self.connections = connections
        self.kwargs = kwargs

    async def get_tools(self, *, server_name):
        return [_DummyTool(name) for name in self.names]


def _config(**server_overrides):
    server = {"transport": "stdio", "command": "npx"}
    server.update(server_overrides)
    return MCPConfig.from_mapping({"mcpServers": {"dyna": server}})


@pytest.fixture
def stub_tools(monkeypatch):
    def install(names):
        _FakeClient.names = names
        monkeypatch.setattr(loader, "MultiServerMCPClient", _FakeClient)

    return install


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
async def test_hitl_and_retry_policies_only_include_loaded_tools(stub_tools):
    stub_tools(["get_problems", "restart_service"])

    result = await load_mcp_tools(
        _config(
            allow_tools=["get_problems"],
            hitl_tools=["restart_service", "get_problems"],
            retry_tools=["restart_service", "get_problems"],
        )
    )

    assert {tool.name for tool in result.tools} == {"get_problems"}
    assert result.hitl_tools == ("get_problems",)
    assert result.retry_tools == ("get_problems",)
