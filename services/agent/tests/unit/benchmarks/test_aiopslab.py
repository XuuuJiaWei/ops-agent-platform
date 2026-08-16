from __future__ import annotations

import pytest

from ops_pilot.benchmarks.aiopslab import AIOpsLabAgent, run_aiopslab_problem
from ops_pilot.config.settings import load_settings


class _Runtime:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def ainvoke_text(self, text: str, **kwargs: object) -> str:
        self.calls.append({"text": text, **kwargs})
        return "submit(['checkout'])"

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_aiopslab_adapter_uses_the_official_orchestrator_seam() -> None:
    runtime = _Runtime()

    async def build_runtime(_settings):
        return runtime

    class Orchestrator:
        instance: Orchestrator | None = None

        def __init__(self, *, results_dir=None) -> None:
            self.results_dir = results_dir
            self.agent = None
            self.agent_name = None
            Orchestrator.instance = self

        def register_agent(self, agent, name: str) -> None:
            self.agent = agent
            self.agent_name = name

        def init_problem(self, problem_id: str):
            assert problem_id == "checkout-localization-1"
            return "Find the faulty service.", "Submit the service name.", {"submit": "submit(name: str)"}

        async def start_problem(self, *, max_steps: int):
            assert max_steps == 2
            assert self.agent is not None
            first_action = await self.agent.get_action("Please take the next action")
            second_action = await self.agent.get_action("Logs identify checkout")
            return {
                "results": {"correct": first_action == second_action},
                "framework_overhead": 1.25,
            }

    result = await run_aiopslab_problem(
        "checkout-localization-1",
        max_steps=2,
        settings=load_settings(env={}, config={}),
        runtime_factory=build_runtime,
        orchestrator_type=Orchestrator,
    )

    assert Orchestrator.instance is not None
    assert Orchestrator.instance.agent_name == "ops-pilot"
    assert runtime.closed is True
    assert result == {
        "benchmark": "aiopslab",
        "problem_id": "checkout-localization-1",
        "task_metrics": {"correct": True},
        "benchmark_metrics": {"actions": 2, "framework_overhead_s": 1.25},
    }
    assert "Available AIOpsLab actions" in str(runtime.calls[0]["text"])
    assert "Find the faulty service." in str(runtime.calls[0]["text"])
    assert "Available AIOpsLab actions" not in str(runtime.calls[1]["text"])
    assert runtime.calls[0]["protocol"] == "benchmark:aiopslab"


@pytest.mark.asyncio
async def test_aiopslab_agent_requires_orchestrator_context() -> None:
    agent = AIOpsLabAgent(_Runtime(), problem_id="case-1")

    with pytest.raises(RuntimeError, match="init_context"):
        await agent.get_action("Please take the next action")


@pytest.mark.asyncio
async def test_aiopslab_run_rejects_an_invalid_step_limit() -> None:
    with pytest.raises(ValueError, match="max_steps"):
        await run_aiopslab_problem("case-1", max_steps=0, orchestrator_type=object)
