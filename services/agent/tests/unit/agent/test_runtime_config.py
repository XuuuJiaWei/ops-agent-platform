from __future__ import annotations

from dataclasses import dataclass

import pytest

from ops_pilot.agent.runtime import AgentRuntime
from ops_pilot.config.settings import load_settings
from ops_pilot.reliability.run import RunController


@dataclass(frozen=True)
class DummyGraph:
    config: dict[str, object] | None = None


def test_runnable_config_forwards_deepagents_recursion_limit_as_top_level_key() -> None:
    runtime = AgentRuntime(
        graph=DummyGraph(config={"recursion_limit": 1234}),
        settings=load_settings(env={}, config={"app_env": "test"}),
    )

    config = runtime.runnable_config(
        protocol="copilotkit-agui",
        thread_id="thread-1",
        configurable={"tenant": "local"},
    )

    assert config.get("recursion_limit") == 1234
    assert config.get("configurable") == {"tenant": "local", "thread_id": "thread-1"}
    metadata = config.get("metadata")
    assert metadata is not None
    assert metadata["langfuse_session_id"] == "thread-1"
    assert metadata["langfuse_trace_name"] == "handle-copilotkit-run"
    assert config.get("run_name") == "handle-copilotkit-run"
    assert config.get("tags") == ["ops_pilot", "copilotkit-agui", "test"]


def test_runnable_config_does_not_invent_recursion_limit_when_graph_has_no_bound_config() -> None:
    runtime = AgentRuntime(graph=object(), settings=load_settings(env={}, config={"app_env": "test"}))

    config = runtime.runnable_config(protocol="smoke")

    assert "recursion_limit" not in config


@pytest.mark.asyncio
async def test_ainvoke_trace_passes_the_case_deadline_to_run_controller() -> None:
    class Graph:
        version: str | None = None

        async def ainvoke(self, *_args, **_kwargs):
            self.version = _kwargs.get("version")
            return {"messages": [{"content": "done"}]}

    class Controller(RunController):
        def __init__(self) -> None:
            super().__init__()
            self.deadline_seconds: float | None = None

        async def run(self, run_id, operation, *, deadline_seconds=None):
            del run_id
            self.deadline_seconds = deadline_seconds
            return await operation()

    controller = Controller()
    runtime = AgentRuntime(
        graph=Graph(),
        settings=load_settings(env={}, config={}),
        run_controller=controller,
    )

    trace = await runtime.ainvoke_trace(
        "hello",
        protocol="eval",
        run_id="case-1",
        deadline_seconds=42,
    )

    assert trace.final_text == "done"
    assert controller.deadline_seconds == 42
    assert runtime.graph.version == "v2"


@pytest.mark.asyncio
async def test_ainvoke_text_never_treats_a_hitl_interrupt_as_final_output() -> None:
    class Result:
        value = {"messages": [{"content": "I will check that now."}]}
        interrupts = (object(),)

    class Graph:
        async def ainvoke(self, *_args, **_kwargs):
            return Result()

    runtime = AgentRuntime(graph=Graph(), settings=load_settings(env={}, config={}))

    with pytest.raises(RuntimeError, match="human approval"):
        await runtime.ainvoke_text("delete the pod", protocol="test")
