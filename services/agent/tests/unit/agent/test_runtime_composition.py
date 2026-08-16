from __future__ import annotations

import pytest

from ops_pilot.agent import runtime as runtime_module
from ops_pilot.mcp.registry import MCPRegistry
from ops_pilot.observability.langfuse import TracingSetup
from ops_pilot.runtime.spec import ModelSpec, RuntimeSpec


@pytest.mark.asyncio
async def test_builder_consumes_only_the_explicit_runtime_spec(monkeypatch) -> None:
    captured: dict[str, object] = {}
    spec = RuntimeSpec(
        id="test-runtime",
        assistant_id="test-agent",
        entrypoint="test",
        model=ModelSpec(provider="openai", name="test-model"),
        tools=("entry-tool",),
        interrupt_on={"dangerous-tool": True},
    )

    monkeypatch.setattr(runtime_module, "create_chat_model", lambda model: captured.setdefault("model", model))

    async def create_registry(catalog):
        captured["catalog"] = catalog
        return MCPRegistry(hitl_tools=("dangerous-tool",))

    monkeypatch.setattr(runtime_module, "create_mcp_registry", create_registry)
    monkeypatch.setattr(runtime_module, "resolve_skill_paths", lambda paths: ())
    monkeypatch.setattr(runtime_module, "create_callback_handler", lambda observability: TracingSetup(False))
    monkeypatch.setattr(runtime_module, "create_sandbox_manager", lambda sandbox: None)
    monkeypatch.setattr(runtime_module, "build_model_metadata", lambda runtime, model: {"runtime": runtime.id})

    def create_agent(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(runtime_module, "_create_deep_agent", create_agent)

    runtime = await runtime_module.build_agent_runtime(spec)

    assert runtime.spec is spec
    assert captured["model"] is spec.model
    assert captured["catalog"] is spec.mcp
    assert captured["tools"] == ["entry-tool"]
    assert captured["interrupt_on"] == {"dangerous-tool": True}


@pytest.mark.asyncio
async def test_automated_runtime_can_declare_no_tool_interrupts(monkeypatch) -> None:
    captured: dict[str, object] = {}
    spec = RuntimeSpec(
        id="benchmark",
        assistant_id="benchmark-agent",
        entrypoint="benchmark",
        model=ModelSpec(provider="openai", name="benchmark-model"),
    )

    monkeypatch.setattr(runtime_module, "create_chat_model", lambda _: object())

    async def create_registry(_):
        return MCPRegistry(hitl_tools=("dangerous-tool",))

    monkeypatch.setattr(runtime_module, "create_mcp_registry", create_registry)
    monkeypatch.setattr(runtime_module, "resolve_skill_paths", lambda _: ())
    monkeypatch.setattr(runtime_module, "create_callback_handler", lambda _: TracingSetup(False))
    monkeypatch.setattr(runtime_module, "create_sandbox_manager", lambda _: None)
    monkeypatch.setattr(runtime_module, "build_model_metadata", lambda *_: {})
    monkeypatch.setattr(runtime_module, "_create_deep_agent", lambda **kwargs: captured.update(kwargs) or object())

    await runtime_module.build_agent_runtime(spec)

    assert captured["interrupt_on"] == {}
