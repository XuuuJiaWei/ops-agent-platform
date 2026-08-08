from dataclasses import dataclass, field
from typing import Any

import pytest

from ops_pilot.agent.manager import AgentRuntimeManager
from ops_pilot.config.settings import load_settings
from ops_pilot.mcp.registry import MCPRegistry


@dataclass
class DummyRuntime:
    tools: tuple[Any, ...] = field(default_factory=tuple)
    mcp: MCPRegistry = field(default_factory=MCPRegistry)
    sandbox: Any | None = None
    closed: bool = False

    def close(self) -> None:
        self.closed = True


@dataclass
class DummySandbox:
    expired: bool = False
    should_renew_value: bool = False
    renew_result: bool = True
    renew_calls: int = 0

    def is_expired(self) -> bool:
        return self.expired

    def should_renew(self) -> bool:
        return self.should_renew_value

    def renew(self) -> bool:
        self.renew_calls += 1
        return self.renew_result


@pytest.mark.asyncio
async def test_runtime_manager_rebuilds_when_sandbox_ttl_expired(monkeypatch) -> None:
    settings = load_settings(env={}, config={"app_env": "test"})
    initial_runtime = DummyRuntime(sandbox=DummySandbox(expired=True))
    rebuilt_runtime = DummyRuntime()

    async def fake_build_agent_runtime(*_: object, **__: object):
        return rebuilt_runtime

    monkeypatch.setattr("ops_pilot.agent.manager.build_agent_runtime", fake_build_agent_runtime)
    manager = AgentRuntimeManager(settings=settings, runtime=initial_runtime)  # type: ignore[arg-type]

    result = await manager.ensure_runtime_ready()

    assert result is not None
    assert manager.current is rebuilt_runtime
    assert initial_runtime.closed is True
    assert result.generation == 1


@pytest.mark.asyncio
async def test_runtime_manager_rebuilds_when_sandbox_renew_reports_missing(monkeypatch) -> None:
    settings = load_settings(env={}, config={"app_env": "test"})
    sandbox = DummySandbox(should_renew_value=True, renew_result=False)
    initial_runtime = DummyRuntime(sandbox=sandbox)
    rebuilt_runtime = DummyRuntime()

    async def fake_build_agent_runtime(*_: object, **__: object):
        return rebuilt_runtime

    monkeypatch.setattr("ops_pilot.agent.manager.build_agent_runtime", fake_build_agent_runtime)
    manager = AgentRuntimeManager(settings=settings, runtime=initial_runtime)  # type: ignore[arg-type]

    result = await manager.ensure_runtime_ready()

    assert result is not None
    assert sandbox.renew_calls == 1
    assert manager.current is rebuilt_runtime
    assert initial_runtime.closed is True
