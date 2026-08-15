"""Run OpsPilot against a Microsoft AIOpsLab localization problem.

AIOpsLab owns the benchmark environment and ground truth. OpsPilot owns the
agent loop and continues to investigate through its configured MCP tools.
"""

from __future__ import annotations

from typing import Any

import httpx
from langchain.tools import tool

from ops_pilot.agent.runtime import build_agent_runtime
from ops_pilot.config.settings import Settings, load_settings


async def run_aiopslab_problem(
    problem_id: str,
    *,
    base_url: str,
    settings: Settings | None = None,
    deadline_seconds: float = 300.0,
) -> dict[str, Any]:
    """Run one localization problem through the external AIOpsLab bridge."""

    base_url = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=900.0) as http:
        start = await http.post(f"{base_url}/runs", json={"problem_id": problem_id})
        start.raise_for_status()
        case: dict[str, Any] = start.json()
        run_id = str(case["run_id"])
        completed = False
        runtime = None
        submitted: list[str] | None = None

        @tool
        def submit_localization(faulty_components: list[str]) -> str:
            """Submit the final faulty service/component names exactly once after gathering evidence."""

            nonlocal submitted
            if submitted is not None:
                return "A localization result was already submitted."
            submitted = [str(component) for component in faulty_components]
            return "Localization result recorded. Finish the investigation."

        try:
            if case.get("task_type") != "localization":
                task_type = case.get("task_type")
                raise ValueError(
                    f"Only AIOpsLab localization is supported in the first benchmark slice; got {task_type!r}."
                )

            runtime = await build_agent_runtime(
                settings=settings or load_settings(),
                attach_checkpointer=False,
                extra_tools=(submit_localization,),
            )
            trace = await runtime.ainvoke_trace(
                _prompt(case),
                protocol="aiopslab",
                thread_id=run_id,
                run_id=f"aiopslab:{run_id}",
                deadline_seconds=deadline_seconds,
                extra_metadata={"benchmark": "aiopslab", "problem_id": problem_id},
            )
            if submitted is None:
                raise RuntimeError("Agent finished without calling submit_localization.")

            response = await http.post(f"{base_url}/runs/{run_id}/evaluate", json={"solution": submitted})
            response.raise_for_status()
            completed = True
            return {
                "problem_id": problem_id,
                "solution": submitted,
                "task_metrics": response.json()["results"],
                "runtime_metrics": {
                    "tool_calls": len(trace.tool_calls),
                    "steps": trace.steps,
                    "latency_s": trace.latency_s,
                },
            }
        finally:
            if runtime is not None:
                await runtime.aclose()
            if not completed:
                try:
                    await http.post(f"{base_url}/runs/{run_id}/abort")
                except httpx.HTTPError:
                    pass


def _prompt(case: dict[str, Any]) -> str:
    namespace = case.get("namespace")
    namespace_hint = f"\nBenchmark namespace: {namespace}" if namespace else ""
    return f"""You are solving an AIOpsLab fault-localization benchmark.

{case["task_description"]}
{namespace_hint}

Investigate with the available read-only observability tools. Do not modify the
benchmark environment. Separate observations from hypotheses. When evidence is
sufficient, call submit_localization exactly once with the faulty component names.
"""
