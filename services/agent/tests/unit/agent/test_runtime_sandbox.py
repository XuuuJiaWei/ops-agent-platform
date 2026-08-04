from __future__ import annotations

from dataclasses import dataclass

import pytest

from ops_pilot.agent import runtime as runtime_module
from ops_pilot.config.settings import load_settings
from ops_pilot.mcp.registry import MCPRegistry
from ops_pilot.observability.langfuse import TracingSetup
from ops_pilot.skills.sync import SkillSyncResult


@dataclass
class DummySandboxRuntime:
    backend: object
    closed: bool = False

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_build_agent_runtime_passes_sandbox_backend(monkeypatch) -> None:
    backend = object()
    sandbox = DummySandboxRuntime(backend=backend)
    captured: dict[str, object] = {}

    monkeypatch.setattr(runtime_module, "create_chat_model", lambda _: object())
    monkeypatch.setattr(runtime_module, "create_mcp_registry", lambda _: _empty_registry())
    monkeypatch.setattr(runtime_module, "resolve_skill_paths", lambda _: [])
    monkeypatch.setattr(runtime_module, "create_callback_handler", lambda _: TracingSetup(False))
    monkeypatch.setattr(runtime_module, "get_smoke_tools", lambda: [])
    monkeypatch.setattr(runtime_module, "create_sandbox_runtime", lambda _: sandbox)

    def fake_create_deep_agent(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runtime_module, "_create_deep_agent", fake_create_deep_agent)

    runtime = await runtime_module.build_agent_runtime(load_settings(env={}, config={"app_env": "test"}))

    assert runtime.sandbox is sandbox
    assert captured["backend"] is backend


@pytest.mark.asyncio
async def test_build_agent_runtime_syncs_skills_into_sandbox(monkeypatch) -> None:
    backend = object()
    sandbox = DummySandboxRuntime(backend=backend)
    captured: dict[str, object] = {}
    synced: dict[str, object] = {}

    monkeypatch.setattr(runtime_module, "create_chat_model", lambda _: object())
    monkeypatch.setattr(runtime_module, "create_mcp_registry", lambda _: _empty_registry())
    monkeypatch.setattr(runtime_module, "resolve_skill_paths", lambda _: ["/local/skills"])
    monkeypatch.setattr(runtime_module, "create_callback_handler", lambda _: TracingSetup(False))
    monkeypatch.setattr(runtime_module, "get_smoke_tools", lambda: [])
    monkeypatch.setattr(runtime_module, "create_sandbox_runtime", lambda _: sandbox)

    def fake_sync_skill_paths(paths: tuple[str, ...], backend_arg: object) -> SkillSyncResult:
        synced["paths"] = paths
        synced["backend"] = backend_arg
        return SkillSyncResult(remote_paths=("/workspace/skills/00-skills",), file_count=1)

    def fake_create_deep_agent(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runtime_module, "sync_skill_paths_to_backend", fake_sync_skill_paths)
    monkeypatch.setattr(runtime_module, "_create_deep_agent", fake_create_deep_agent)

    runtime = await runtime_module.build_agent_runtime(load_settings(env={}, config={"app_env": "test"}))

    assert synced == {"paths": ("/local/skills",), "backend": backend}
    assert runtime.skills == ("/workspace/skills/00-skills",)
    assert captured["skills"] == ["/workspace/skills/00-skills"]


@pytest.mark.asyncio
async def test_build_agent_runtime_closes_sandbox_when_graph_creation_fails(monkeypatch) -> None:
    sandbox = DummySandboxRuntime(backend=object())

    monkeypatch.setattr(runtime_module, "create_chat_model", lambda _: object())
    monkeypatch.setattr(runtime_module, "create_mcp_registry", lambda _: _empty_registry())
    monkeypatch.setattr(runtime_module, "resolve_skill_paths", lambda _: [])
    monkeypatch.setattr(runtime_module, "create_callback_handler", lambda _: TracingSetup(False))
    monkeypatch.setattr(runtime_module, "get_smoke_tools", lambda: [])
    monkeypatch.setattr(runtime_module, "create_sandbox_runtime", lambda _: sandbox)

    def fake_create_deep_agent(**_: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime_module, "_create_deep_agent", fake_create_deep_agent)

    with pytest.raises(RuntimeError, match="boom"):
        await runtime_module.build_agent_runtime(load_settings(env={}, config={"app_env": "test"}))

    assert sandbox.closed is True


async def _empty_registry() -> MCPRegistry:
    return MCPRegistry()


async def _hitl_registry() -> MCPRegistry:
    return MCPRegistry(hitl_tools=("restart_service", "delete_entity"))


@pytest.mark.asyncio
async def test_build_agent_runtime_builds_interrupt_on_from_hitl_tools(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(runtime_module, "create_chat_model", lambda _: object())
    monkeypatch.setattr(runtime_module, "create_mcp_registry", lambda _: _hitl_registry())
    monkeypatch.setattr(runtime_module, "resolve_skill_paths", lambda _: [])
    monkeypatch.setattr(runtime_module, "create_callback_handler", lambda _: TracingSetup(False))
    monkeypatch.setattr(runtime_module, "get_smoke_tools", lambda: [])
    monkeypatch.setattr(runtime_module, "create_sandbox_runtime", lambda _: None)

    def fake_create_deep_agent(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runtime_module, "_create_deep_agent", fake_create_deep_agent)

    await runtime_module.build_agent_runtime(load_settings(env={}, config={"app_env": "test"}))

    assert captured["interrupt_on"] == {"restart_service": True, "delete_entity": True}
