"""Minimal external-agent bridge for Microsoft AIOpsLab.

Run this file inside the AIOpsLab environment. It deliberately reuses AIOpsLab's
official Orchestrator/Session/Problem objects and exposes only the lifecycle
OpsPilot needs: start, evaluate, abort.
"""

from __future__ import annotations

import asyncio
import atexit
import inspect
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from aiopslab.orchestrator import Orchestrator
from aiopslab.orchestrator.orchestrator import exit_cleanup_fault
from aiopslab.service.telemetry.prometheus import Prometheus
from aiopslab.session import Session
from aiopslab.utils.critical_section import CriticalSection
from fastapi import FastAPI, HTTPException
from problems.astronomy_shop_faults import CUSTOM_PROBLEM_REGISTRY

app = FastAPI(title="AIOpsLab OpsPilot Bridge")
_active: dict[str, Any] | None = None
_lock = asyncio.Lock()
_OBSERVER_RBAC = Path(__file__).resolve().parent / "rbac" / "observer.yaml"


def _persistent_default() -> bool:
    """Env default for warm-run mode (``AIOPSLAB_PERSISTENT``, default on).

    Each ``POST /runs`` may override this with a ``persistent`` boolean field,
    so callers can switch between warm runs and the official one-shot lifecycle
    without restarting the bridge.
    """
    return os.getenv("AIOPSLAB_PERSISTENT", "1").lower() not in {"0", "false", "no"}


def _problem_is_persistent(problem: Any) -> bool:
    return bool(getattr(problem, "PERSISTENT", False))


def _app_is_ready(namespace: str, kubectl: Any) -> bool:
    """Return True when the app namespace exists and every pod is ready."""
    try:
        pod_list = kubectl.list_pods(namespace)
    except Exception:  # noqa: BLE001 - missing namespace etc.
        return False
    return bool(pod_list.items) and all(
        kubectl._pod_is_ready_or_succeeded(pod) for pod in pod_list.items
    )


def _register_custom_problems(orchestrator: Orchestrator) -> None:
    """Register non-flag (Chaos Mesh) astronomy-shop problems on the registry."""
    for problem_id, factory in CUSTOM_PROBLEM_REGISTRY.items():
        orchestrator.probs.PROBLEM_REGISTRY[problem_id] = factory


def _init_custom_problem(
    orchestrator: Orchestrator, problem_id: str, problem: Any
) -> tuple[str, str, Any]:
    """Mirror ``Orchestrator.init_problem`` but keep a warm app when healthy.

    OpenEBS and Prometheus setup are idempotent (Prometheus already skips when
    its release is deployed); the app delete/redeploy is skipped whenever the
    namespace is present and all pods are Ready.
    """
    orchestrator.execution_start_time = time.time()
    orchestrator.session = Session(results_dir=orchestrator.results_dir)
    print(f"Session ID: {orchestrator.session.session_id}")
    deployment = orchestrator.probs.get_problem_deployment(problem_id)
    orchestrator.session.set_problem(problem, pid=problem_id)
    orchestrator.session.set_agent(orchestrator.agent_name)

    if deployment != "docker":
        print("Ensuring OpenEBS and Prometheus...")
        kubectl = orchestrator.kubectl
        kubectl.exec_command(
            "kubectl apply -f https://openebs.github.io/charts/openebs-operator.yaml"
        )
        kubectl.exec_command(
            'kubectl patch storageclass openebs-hostpath -p \'{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}\''
        )
        kubectl.wait_for_ready("openebs")
        orchestrator.prometheus = Prometheus()
        orchestrator.prometheus.deploy()

    if _app_is_ready(problem.namespace, orchestrator.kubectl):
        print(f"App {problem.namespace!r} is healthy; skipping redeploy.")
    else:
        print(f"App {problem.namespace!r} missing or not ready; deploying...")
        problem.app.delete()
        problem.app.deploy()

    with CriticalSection():
        problem.inject_fault()
        atexit.register(exit_cleanup_fault, prob=problem)

    if inspect.iscoroutinefunction(problem.start_workload):
        asyncio.create_task(problem.start_workload())
    else:
        problem.start_workload()

    return (
        problem.get_task_description(),
        problem.get_instructions(),
        problem.get_available_actions(),
    )


def _ensure_observer_rbac() -> None:
    """(Re)create the agent's read-only observer identity in the app namespace.

    Every benchmark run tears down and recreates the app namespace, which also
    deletes the namespaced Role/RoleBinding. Re-applying after ``init_problem``
    keeps the agent's restricted identity available without touching its token
    (the ServiceAccount lives in the stable ``ops-pilot`` namespace).
    """
    if not _OBSERVER_RBAC.exists():
        return
    subprocess.run(["kubectl", "apply", "-f", str(_OBSERVER_RBAC)], check=False)


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
            raise HTTPException(
                status_code=409, detail="another benchmark run is active"
            )

        orchestrator = Orchestrator()
        _register_custom_problems(orchestrator)
        orchestrator.register_agent(object(), name="ops-pilot")
        requested = payload.get("persistent")
        persistent = requested if isinstance(requested, bool) else _persistent_default()
        try:
            use_persistent = False
            if persistent and problem_id in CUSTOM_PROBLEM_REGISTRY:
                problem = orchestrator.probs.get_problem_instance(problem_id)
                use_persistent = _problem_is_persistent(problem)
                if use_persistent:
                    print(
                        "Persistent environment mode enabled; warm runs reuse the app."
                    )
            if use_persistent:
                description, _instructions, _actions = await asyncio.to_thread(
                    _init_custom_problem, orchestrator, problem_id, problem
                )
            else:
                description, _instructions, _actions = await asyncio.to_thread(
                    orchestrator.init_problem, problem_id
                )
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"AIOpsLab init failed: {exc}"
            ) from exc

        _ensure_observer_rbac()
        assert orchestrator.session is not None
        orchestrator.session.start()
        run_id = uuid.uuid4().hex
        _active = {
            "run_id": run_id,
            "problem_id": problem_id,
            "orchestrator": orchestrator,
            "persistent": use_persistent,
        }

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
        results = await asyncio.to_thread(
            session.problem.eval, solution, [], session.get_duration()
        )
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
    persistent = bool(active.get("persistent"))

    def cleanup() -> None:
        if session is None or session.problem is None:
            return
        problem = session.problem
        with CriticalSection():
            try:
                problem.recover_fault()
            finally:
                atexit.unregister(exit_cleanup_fault)
                if not persistent:
                    problem.app.cleanup()
        if not persistent:
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
        else:
            print(
                "Persistent mode: app, Prometheus and OpenEBS kept warm for the next run."
            )

    try:
        await asyncio.to_thread(cleanup)
    finally:
        async with _lock:
            if _active is active:
                _active = None


def _task_type(problem_id: str) -> str:
    return next(
        (
            task
            for task in ("detection", "localization", "analysis", "mitigation")
            if f"-{task}" in problem_id
        ),
        "unknown",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("AIOPSLAB_BRIDGE_HOST", "0.0.0.0"),
        port=int(os.getenv("AIOPSLAB_BRIDGE_PORT", "1819")),
    )
