"""Minimal external-agent bridge for Microsoft AIOpsLab.

Run this file inside the AIOpsLab environment. It deliberately reuses AIOpsLab's
official Orchestrator/Session/Problem objects and exposes only the lifecycle
OpsPilot needs: start, evaluate, abort.
"""

from __future__ import annotations

import atexit
import asyncio
import os
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException

from aiopslab.orchestrator import Orchestrator
from aiopslab.orchestrator.orchestrator import exit_cleanup_fault
from aiopslab.utils.critical_section import CriticalSection

app = FastAPI(title="AIOpsLab OpsPilot Bridge")
_active: dict[str, Any] | None = None
_lock = asyncio.Lock()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/runs")
async def start_run(payload: dict[str, Any]) -> dict[str, Any]:
    global _active
    problem_id = str(payload.get("problem_id") or "")
    if not problem_id:
        raise HTTPException(status_code=422, detail="problem_id is required")

    async with _lock:
        if _active is not None:
            raise HTTPException(status_code=409, detail="another benchmark run is active")

        orchestrator = Orchestrator()
        orchestrator.register_agent(object(), name="ops-pilot")
        try:
            description, _instructions, _actions = await asyncio.to_thread(orchestrator.init_problem, problem_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"AIOpsLab init failed: {exc}") from exc

        assert orchestrator.session is not None
        orchestrator.session.start()
        run_id = uuid.uuid4().hex
        _active = {"run_id": run_id, "problem_id": problem_id, "orchestrator": orchestrator}

    problem = orchestrator.session.problem
    return {
        "run_id": run_id,
        "problem_id": problem_id,
        "task_type": _task_type(problem_id),
        "task_description": description,
        "namespace": getattr(problem, "namespace", None),
    }


@app.post("/runs/{run_id}/evaluate")
async def evaluate_run(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    active = await _require_active(run_id)
    orchestrator: Orchestrator = active["orchestrator"]
    session = orchestrator.session
    assert session is not None

    try:
        solution = payload.get("solution")
        session.set_solution(solution)
        session.end()
        results = await asyncio.to_thread(session.problem.eval, solution, [], session.get_duration())
        session.set_results(results)
        return {"results": results}
    finally:
        await _finish(active)


@app.post("/runs/{run_id}/abort")
async def abort_run(run_id: str) -> dict[str, str]:
    active = await _require_active(run_id)
    await _finish(active)
    return {"status": "aborted"}


async def _require_active(run_id: str) -> dict[str, Any]:
    async with _lock:
        if _active is None or _active["run_id"] != run_id:
            raise HTTPException(status_code=404, detail="unknown run_id")
        return _active


async def _finish(active: dict[str, Any]) -> None:
    global _active
    orchestrator: Orchestrator = active["orchestrator"]
    session = orchestrator.session

    def cleanup() -> None:
        if session is None or session.problem is None:
            return
        problem = session.problem
        with CriticalSection():
            try:
                problem.recover_fault()
            finally:
                atexit.unregister(exit_cleanup_fault)
                problem.app.cleanup()
        prometheus = getattr(orchestrator, "prometheus", None)
        if prometheus is not None:
            prometheus.teardown()
        if getattr(problem, "namespace", None) != "docker":
            orchestrator.kubectl.exec_command(
                "kubectl delete sc openebs-hostpath openebs-device --ignore-not-found"
            )
            orchestrator.kubectl.exec_command(
                "kubectl delete -f https://openebs.github.io/charts/openebs-operator.yaml --ignore-not-found"
            )

    try:
        await asyncio.to_thread(cleanup)
    finally:
        async with _lock:
            if _active is active:
                _active = None


def _task_type(problem_id: str) -> str:
    return next(
        (task for task in ("detection", "localization", "analysis", "mitigation") if f"-{task}" in problem_id),
        "unknown",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("AIOPSLAB_BRIDGE_HOST", "0.0.0.0"),
        port=int(os.getenv("AIOPSLAB_BRIDGE_PORT", "1819")),
    )
