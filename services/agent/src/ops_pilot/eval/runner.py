"""Eval runner — unified path via langfuse.run_experiment(data=items)."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langfuse import get_client
from langfuse.experiment import ExperimentResult

from ops_pilot.agent.factory import create_agent_runtime_async
from ops_pilot.config.settings import Settings, load_settings
from ops_pilot.eval.dataset import (
    EvalDatasetError,
    load_cases_from_yaml,
    validate_expected_tool_names,
)
from ops_pilot.eval.graders import (
    build_item_evaluators,
    category_pass_rates,
    conditional_task_pass_rate,
    infrastructure_completion_rate,
    infrastructure_error_rates,
    judge_calibration_check,
    pass_rate,
    pass_rate_wilson_lower,
    run_performance_metrics,
)
from ops_pilot.observability.langfuse import (
    TracingSetup,
    finish_observation,
    flush_tracing,
    observation,
)


@dataclass(frozen=True)
class EvalRunSummary:
    result: ExperimentResult
    pass_rate: float
    exit_code: int


# Tiered CI gates (see docs/design/agent-eval.md §10).
#
# HARD gates fail the run (exit 1): safety must be perfect, the judge must not
# have drifted (calibration agreement == 1.0 when sentinels are present), and
# infrastructure must mostly complete. SOFT gates only warn: the Wilson lower
# bound is compared against --min-pass-rate so a tiny suite cannot silently
# "pass" a threshold it lacks the statistical power to support.
HARD_GATES: dict[str, float] = {
    "judge_calibration_agreement": 1.0,
    "infrastructure_completion_rate": 0.95,
}


async def run_eval(
    dataset_name: str,
    *,
    settings: Settings | None = None,
    run_name: str = "local",
    concurrency: int = 4,
    min_pass_rate: float | None = None,
    cases_dir: str | Path,
    only: list[str] | None = None,
) -> EvalRunSummary:
    resolved_settings = settings or load_settings()
    if concurrency <= 0:
        raise ValueError("concurrency must be greater than 0")
    if min_pass_rate is not None and not 0 <= min_pass_rate <= 1:
        raise ValueError("min_pass_rate must be between 0 and 1")

    # Always load from local YAML — no Langfuse dataset fetch required.
    cases = tuple(load_cases_from_yaml(cases_dir))
    if only:
        cases = tuple(c for c in cases if c.id in set(only))
        if not cases:
            raise ValueError(f"--only matched no cases. Requested: {sorted(only)}")

    inject_cases = [c.id for c in cases if c.inject]
    if inject_cases:
        raise EvalDatasetError(
            f"eval run cannot execute inject-bearing cases — use 'chaos run' instead. "
            f"Offending cases ({len(inject_cases)}): {', '.join(inject_cases)}. "
            f"Move them to ops_chaos_scenarios.yaml or pass a --cases-dir without them."
        )

    runtime = await create_agent_runtime_async(settings=resolved_settings, attach_checkpointer=False, bypass_hitl=True)
    try:
        validate_expected_tool_names(cases, _runtime_tool_names(runtime))
        async_task = _build_task(runtime, run_name=run_name)

        # get_client() is always safe: returns a no-op singleton when Langfuse
        # is not configured. run_experiment executes task + evaluators locally
        # regardless; connectivity only affects whether traces are uploaded.
        langfuse = get_client()
        items = [case.to_experiment_item() for case in cases]
        runtime_loop = asyncio.get_running_loop()
        item_evaluators = [_ensure_sync(ev, runtime_loop) for ev in build_item_evaluators(resolved_settings, include_judge=True)]

        def execute_experiment() -> ExperimentResult:
            def sync_task(*, item: Any, **_: Any) -> Any:
                # Langfuse 4.x runs tasks inside its own event loop, so
                # asyncio.run() would fail with "cannot be called from a
                # running event loop". Schedule onto the runtime loop instead
                # and block this thread until the coroutine completes.
                future = asyncio.run_coroutine_threadsafe(async_task(item=item), runtime_loop)
                return future.result()

            return langfuse.run_experiment(
                name="ops_pilot eval",
                run_name=run_name,
                description="ops_pilot agent evaluation run",
                data=items,
                task=sync_task,
                evaluators=item_evaluators,
                run_evaluators=[
                    pass_rate,
                    pass_rate_wilson_lower,
                    judge_calibration_check,
                    infrastructure_completion_rate,
                    conditional_task_pass_rate,
                    infrastructure_error_rates,
                    category_pass_rates,
                    run_performance_metrics,
                ],
                max_concurrency=concurrency,
                metadata=_run_metadata(runtime, dataset_name=dataset_name),
            )

        result = await asyncio.to_thread(execute_experiment)
    finally:
        flush_tracing(runtime.tracing)
        await _close_runtime(runtime)

    print(result.format())
    overall = _run_evaluation_value(result, "pass_rate")
    exit_code = _evaluate_gates(result, min_pass_rate=min_pass_rate)
    return EvalRunSummary(result=result, pass_rate=overall, exit_code=exit_code)


def _evaluate_gates(result: ExperimentResult, *, min_pass_rate: float | None) -> int:
    """Apply tiered CI gates. HARD gate failure => exit 1; SOFT gate => warn only."""

    scores = {
        evaluation.name: evaluation.value
        for evaluation in result.run_evaluations
        if isinstance(evaluation.value, int | float)
    }
    exit_code = 0
    for metric, threshold in HARD_GATES.items():
        value = scores.get(metric)
        if value is None:
            # Metric absent (e.g. no safety cases / no sentinels in this run) —
            # nothing to gate on. Skip rather than fail.
            continue
        if value < threshold:
            print(f"HARD GATE FAILED: {metric}={value:.3f} < {threshold:.3f}.")
            exit_code = 1

    if min_pass_rate is not None:
        lower = scores.get("pass_rate_wilson_lower")
        if lower is not None and lower < min_pass_rate:
            print(
                f"soft gate warning: pass_rate_wilson_lower {lower:.3f} is below "
                f"{min_pass_rate:.3f} (point pass_rate={scores.get('pass_rate', 0.0):.3f}). "
                "Sample size may be too small to support this threshold."
            )
    return exit_code


def _ensure_sync(evaluator: Any, loop: asyncio.AbstractEventLoop) -> Any:
    """Wrap an async evaluator so Langfuse's synchronous SDK can call it."""
    if not inspect.iscoroutinefunction(evaluator):
        return evaluator

    def sync_ev(**kwargs: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(evaluator(**kwargs), loop)
        return future.result()

    sync_ev.__name__ = getattr(evaluator, "__name__", "evaluator")
    return sync_ev


def _build_task(runtime: Any, *, run_name: str) -> Any:
    # Persistent MCP sessions belong to the loop that created the runtime.
    # Langfuse's synchronous experiment API executes async tasks on a worker loop,
    # so all runtime work is dispatched back here.
    runtime_loop = asyncio.get_running_loop()

    async def invoke(
        *,
        input_text: str,
        case_id: str,
        metadata: Mapping[str, Any],
        timeout_s: float,
    ) -> Any:
        # Keep runtime work in a child task so cancellation cleanup stays on the
        # event loop that owns the persistent MCP sessions. The only deadline is
        # enforced by RunController inside AgentRuntime.
        invocation = asyncio.create_task(
            runtime.ainvoke_trace(
                input_text,
                protocol="eval",
                thread_id=f"eval-{case_id}",
                run_id=f"{run_name}:{case_id}",
                extra_metadata={
                    "eval_case_id": case_id,
                    "eval_category": metadata.get("category"),
                    "eval_run_name": run_name,
                    "eval_timeout_seconds": timeout_s,
                },
                deadline_seconds=timeout_s,
            ),
            name=f"eval-{case_id}",
        )
        try:
            return await invocation
        except BaseException:
            if not invocation.done():
                invocation.cancel()
                await asyncio.gather(invocation, return_exceptions=True)
            raise

    async def task(*, item: Any, **_: Any) -> dict[str, Any]:
        input_text = _item_input(item)
        metadata = _item_metadata(item)
        case_id = _case_id(item, metadata=metadata, input_text=input_text)

        # Sentinel short-circuit: a fixed_output case never runs the agent — it
        # feeds canned text straight to the judges so we can verify the JUDGE
        # itself (drift detection), not the agent. No cluster / LLM-agent needed.
        fixed_output = metadata.get("fixed_output")
        if fixed_output:
            return {
                "final_text": str(fixed_output),
                "tool_calls": [],
                "steps": 0,
                "latency_s": 0.0,
                "error": None,
            }

        timeout_s = _timeout_s(metadata)
        started = time.perf_counter()
        tracing = getattr(runtime, "tracing", TracingSetup(enabled=False))
        with observation(
            tracing,
            name="execute-agent",
            as_type="agent",
            input=input_text,
            metadata={
                "eval_case_id": case_id,
                "eval_category": metadata.get("category"),
                "eval_run_name": run_name,
                "deadline_seconds": timeout_s,
                "expected_output": _item_expected_output(item),
            },
        ) as current:
            try:
                invocation = invoke(
                    input_text=input_text,
                    case_id=case_id,
                    metadata=metadata,
                    timeout_s=timeout_s,
                )
                current_loop = asyncio.get_running_loop()
                if current_loop is runtime_loop:
                    trace = await invocation
                else:
                    trace = await _run_on_loop(invocation, runtime_loop)
                output = trace.as_output()
                finish_observation(
                    current,
                    output=output.get("final_text"),
                    metadata={
                        "latency_seconds": output.get("latency_s"),
                        "steps": output.get("steps"),
                    },
                )
                return output
            except Exception as exc:  # noqa: BLE001 - task errors are scored by no_error.
                latency_s = time.perf_counter() - started
                output = {
                    "final_text": "",
                    "tool_calls": [],
                    "steps": 0,
                    "latency_s": latency_s,
                    "error": str(exc) or type(exc).__name__,
                    "error_type": type(exc).__name__,
                    "recursion_limit_hit": _is_recursion_limit_exception(exc),
                }
                finish_observation(
                    current,
                    output=output,
                    error=exc,
                    metadata={"latency_seconds": latency_s},
                )
                return output

    return task


async def _run_on_loop(coro: Any, loop: asyncio.AbstractEventLoop) -> Any:
    """Run loop-bound runtime work from an SDK worker event loop."""

    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return await asyncio.wrap_future(future)
    except asyncio.CancelledError:
        future.cancel()
        try:
            await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            pass
        raise


async def _close_runtime(runtime: Any) -> None:
    aclose = getattr(runtime, "aclose", None)
    if aclose is not None:
        await aclose()
        return
    close = getattr(runtime, "close", None)
    if close is not None:
        close()


def _item_input(item: Any) -> str:
    value = item.get("input") if isinstance(item, Mapping) else getattr(item, "input", None)
    if value is None:
        raise ValueError("Eval item is missing input.")
    return str(value)


def _item_expected_output(item: Any) -> Any:
    return item.get("expected_output") if isinstance(item, Mapping) else getattr(item, "expected_output", None)


def _item_metadata(item: Any) -> dict[str, Any]:
    value = item.get("metadata") if isinstance(item, Mapping) else getattr(item, "metadata", None)
    return dict(value) if isinstance(value, Mapping) else {}


def _case_id(item: Any, *, metadata: Mapping[str, Any], input_text: str) -> str:
    item_id = metadata.get("id") or getattr(item, "id", None)
    if item_id:
        return str(item_id)
    return str(abs(hash(input_text)))


def _timeout_s(metadata: Mapping[str, Any]) -> float:
    value = metadata.get("timeout_s", 60.0)
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = 60.0
    return max(0.1, timeout)


def _is_recursion_limit_exception(exc: Exception) -> bool:
    return type(exc).__name__ == "GraphRecursionError" or "recursion limit" in str(exc).lower()


def _run_evaluation_value(result: ExperimentResult, name: str) -> float:
    for evaluation in result.run_evaluations:
        if evaluation.name == name and isinstance(evaluation.value, int | float):
            return float(evaluation.value)
    return 0.0


def _runtime_tool_names(runtime: Any) -> tuple[str, ...]:
    return tuple(str(tool.name) for tool in getattr(runtime, "tools", ()) if getattr(tool, "name", None))


def _run_metadata(runtime: Any, *, dataset_name: str) -> dict[str, Any]:
    names = sorted(_runtime_tool_names(runtime))
    fingerprint = hashlib.sha256("\0".join(names).encode()).hexdigest()
    return {
        "runner": "ops_pilot.eval",
        "evaluator_version": 2,
        "dataset_name": dataset_name,
        "toolset_size": len(names),
        "toolset_sha256": fingerprint,
        "model": runtime.model_metadata.get("model_name"),
    }
