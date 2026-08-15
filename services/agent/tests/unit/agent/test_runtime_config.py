from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from ops_pilot.agent.runtime import AgentRuntime
from ops_pilot.config.settings import load_settings
from ops_pilot.reliability.run import RunController


@pytest.mark.asyncio
async def test_ainvoke_trace_passes_the_case_deadline_to_run_controller() -> None:
    class Graph:
        version: str | None = None

        async def ainvoke(self, *_args, **_kwargs):
            self.version = _kwargs.get("version")
            return {"messages": [AIMessage("done")]}

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
        value = {"messages": [AIMessage("I will check that now.")]}
        interrupts = (object(),)

    class Graph:
        async def ainvoke(self, *_args, **_kwargs):
            return Result()

    runtime = AgentRuntime(graph=Graph(), settings=load_settings(env={}, config={}))

    with pytest.raises(RuntimeError, match="human approval"):
        await runtime.ainvoke_text("delete the pod", protocol="test")
