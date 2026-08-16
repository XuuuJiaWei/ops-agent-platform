"""Official AIOpsLab SDK adapter.

AIOpsLab owns the problem lifecycle, environment actions, session trace, and
evaluation.  This module only adapts OpsPilot's generic text-agent interface
to AIOpsLab's documented ``Agent.get_action`` interface.
"""

from __future__ import annotations

import importlib
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ops_pilot.agent.runtime import build_agent_runtime
from ops_pilot.benchmarks.contracts import RuntimeFactory, TextAgent
from ops_pilot.entrypoints.benchmark import build_benchmark_runtime_spec
from ops_pilot.runtime.spec import RuntimeSpec


class AIOpsLabAgent:
    """Present a generic text agent through AIOpsLab's ``get_action`` seam."""

    def __init__(self, runtime: TextAgent, *, problem_id: str) -> None:
        self._runtime = runtime
        self._problem_id = problem_id
        self._thread_id = f"aiopslab:{problem_id}:{uuid.uuid4()}"
        self._context: str | None = None
        self._initialized = False
        self.action_count = 0

    def init_context(self, problem_description: str, instructions: str, actions: Mapping[str, str]) -> None:
        """Accept the context supplied by AIOpsLab before its action loop starts."""

        action_docs = "\n\n".join(f"{name}\n{description}" for name, description in actions.items())
        self._context = f"""You are solving the AIOpsLab problem `{self._problem_id}`.

Problem description:
{problem_description}

Benchmark instructions:
{instructions}

Available AIOpsLab actions:
{action_docs}

For every turn, return exactly one valid AIOpsLab action invocation. Do not add
explanation, Markdown, or an action that is absent from the available actions.
"""
        self._initialized = True

    async def get_action(self, state: str) -> str:
        """Return the next action requested by AIOpsLab's orchestrator."""

        if not self._initialized:
            raise RuntimeError("AIOpsLab called get_action before init_context.")
        context = self._context
        self._context = None
        self.action_count += 1
        prompt = f"{context + chr(10) * 2 if context else ''}Current environment state:\n{state}"
        return await self._runtime.ainvoke_text(
            prompt,
            protocol="benchmark:aiopslab",
            thread_id=self._thread_id,
            run_id=self._thread_id,
            extra_metadata={"benchmark": "aiopslab", "problem_id": self._problem_id},
        )


async def run_aiopslab_problem(
    problem_id: str,
    *,
    max_steps: int = 30,
    runtime_spec: RuntimeSpec | None = None,
    results_dir: Path | None = None,
    runtime_factory: RuntimeFactory = build_agent_runtime,
    orchestrator_type: type[Any] | None = None,
) -> dict[str, Any]:
    """Evaluate OpsPilot through AIOpsLab's official ``Orchestrator`` SDK."""

    if max_steps < 1:
        raise ValueError("max_steps must be at least 1.")

    if orchestrator_type is None:
        orchestrator_type = _load_orchestrator()

    runtime = await runtime_factory(runtime_spec or build_benchmark_runtime_spec())
    try:
        agent = AIOpsLabAgent(runtime, problem_id=problem_id)
        orchestrator = orchestrator_type(results_dir=results_dir)
        orchestrator.register_agent(agent, name="ops-pilot")
        description, instructions, actions = orchestrator.init_problem(problem_id)
        agent.init_context(description, instructions, actions)
        outcome = await orchestrator.start_problem(max_steps=max_steps)
        return {
            "benchmark": "aiopslab",
            "problem_id": problem_id,
            "task_metrics": outcome["results"],
            "benchmark_metrics": {
                "actions": agent.action_count,
                "framework_overhead_s": outcome.get("framework_overhead"),
            },
        }
    finally:
        await runtime.aclose()


def _load_orchestrator() -> type[Any]:
    try:
        module = importlib.import_module("aiopslab.orchestrator")
    except ModuleNotFoundError as exc:
        if exc.name == "aiopslab" or (exc.name and exc.name.startswith("aiopslab.")):
            raise RuntimeError(
                "AIOpsLab is not installed. Follow its official installation guide: "
                "clone microsoft/AIOpsLab with --recurse-submodules, then install it into this uv environment."
            ) from exc
        raise
    return module.__dict__["Orchestrator"]
