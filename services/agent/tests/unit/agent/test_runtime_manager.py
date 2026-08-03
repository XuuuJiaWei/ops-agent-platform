from dataclasses import dataclass, field
from typing import Any

import pytest

from ops_pilot.agent.manager import AgentRuntimeManager
from ops_pilot.config.mcp_schema import MCPServerConfig
from ops_pilot.config.settings import load_settings
from ops_pilot.mcp.registry import MCPRegistry
from ops_pilot.mcp.status import MCPLoadStatus, MCPServerLoadStatus


@dataclass
class DummyRuntime:
    tools: tuple[Any, ...] = field(default_factory=tuple)
    mcp: MCPRegistry = field(default_factory=MCPRegistry)


@dataclass(frozen=True)
class DummyTool:
    name: str


@pytest.mark.asyncio
async def test_runtime_manager_applies_dynamic_mcp_server(monkeypatch) -> None:
    settings = load_settings({"APP_ENV": "test"})
    initial_runtime = DummyRuntime()

    async def fake_build_agent_runtime(
        settings_arg,
        *,
        dynamic_mcp_config,
        use_memory_checkpointer,
    ):
        assert settings_arg is settings
        assert use_memory_checkpointer is True
        assert dynamic_mcp_config.servers[0].name == "local-dev"
        return DummyRuntime(
            tools=(DummyTool("local_tool"),),
            mcp=MCPRegistry(
                tools=(DummyTool("local_tool"),),
                status=MCPLoadStatus(
                    config_path="dynamic",
                    servers=(
                        MCPServerLoadStatus(
                            name="local-dev",
                            required=True,
                            transport="streamable_http",
                            ok=True,
                            tool_count=1,
                        ),
                    ),
                ),
            ),
        )

    monkeypatch.setattr("ops_pilot.agent.manager.build_agent_runtime", fake_build_agent_runtime)
    manager = AgentRuntimeManager(settings=settings, runtime=initial_runtime)  # type: ignore[arg-type]

    result = await manager.apply_mcp_server(
        MCPServerConfig(
            name="local-dev",
            transport="streamable_http",
            required=True,
            url="http://127.0.0.1:8123/dev/mcp-tunnels/local-dev/mcp",
        )
    )

    assert manager.current is result.runtime
    assert result.generation == 1
    assert result.dynamic_mcp.tool_count == 1
    assert result.as_dict()["tools"] == ["local_tool"]


@pytest.mark.asyncio
async def test_runtime_manager_keeps_current_runtime_when_reload_fails(monkeypatch) -> None:
    settings = load_settings({"APP_ENV": "test"})
    initial_runtime = DummyRuntime()

    async def fake_build_agent_runtime(*_: object, **__: object):
        raise RuntimeError("load failed")

    monkeypatch.setattr("ops_pilot.agent.manager.build_agent_runtime", fake_build_agent_runtime)
    manager = AgentRuntimeManager(settings=settings, runtime=initial_runtime)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="load failed"):
        await manager.apply_mcp_server(
            MCPServerConfig(
                name="local-dev",
                transport="streamable_http",
                required=True,
                url="http://127.0.0.1:8123/dev/mcp-tunnels/local-dev/mcp",
            )
        )

    assert manager.current is initial_runtime
    assert manager.status().generation == 0
