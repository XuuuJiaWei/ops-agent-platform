from __future__ import annotations

import pytest
from ops_pilot.runtime.spec import ModelSpec, RuntimeSpec

from ops_pilot_platform.benchmarks.aiopslab import run_aiopslab_problem
from ops_pilot_platform.benchmarks.contracts import TextAgent


class Runtime(TextAgent):
    closed = False

    async def ainvoke_text(
        self,
        text: str,
        *,
        protocol: str,
        thread_id: str | None = None,
        run_id: str | None = None,
        extra_metadata: dict[str, object] | None = None,
    ) -> str:
        del text, protocol, thread_id, run_id, extra_metadata
        return "submit(['checkout'])"

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_benchmark_receives_a_dedicated_runtime_composition() -> None:
    received: list[RuntimeSpec] = []
    runtime = Runtime()
    spec = RuntimeSpec(
        id="benchmark-test",
        assistant_id="benchmark-test-agent",
        entrypoint="benchmark:aiopslab",
        model=ModelSpec(provider="openai", name="benchmark-model"),
    )

    async def factory(candidate: RuntimeSpec) -> Runtime:
        received.append(candidate)
        return runtime

    class Orchestrator:
        def __init__(self, **_: object) -> None:
            self.agent = None

        def register_agent(self, agent, name: str) -> None:
            assert name == "ops-pilot"
            self.agent = agent

        def init_problem(self, _problem_id: str):
            return "Find checkout", "Submit the service", {"submit": "submit(name: str)"}

        async def start_problem(self, *, max_steps: int):
            assert self.agent is not None
            await self.agent.get_action("state")
            return {"results": {"ok": True}, "framework_overhead": 0.1}

    result = await run_aiopslab_problem(
        "checkout-localization-1",
        max_steps=2,
        runtime_spec=spec,
        runtime_factory=factory,
        orchestrator_type=Orchestrator,
    )

    assert received == [spec]
    assert runtime.closed is True
    assert result["benchmark"] == "aiopslab"
