"""Eval runner for Langfuse-backed and local offline runs."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langfuse.experiment import ExperimentItemResult, ExperimentResult

from ops_pilot.agent.factory import create_agent_runtime_async
from ops_pilot.config.settings import Settings, load_settings
from ops_pilot.eval.dataset import (
    DEFAULT_CASES_DIR,
    EvalCase,
    close_langfuse_client,
    create_langfuse_client,
    langfuse_client_is_reachable,
    load_cases_from_yaml,
    sync_cases_to_langfuse,
    validate_dataset_schema,
    validate_expected_tool_names,
)
from ops_pilot.eval.graders import (
    build_item_evaluators,
    category_pass_rates,
    conditional_task_pass_rate,
    infrastructure_completion_rate,
    infrastructure_error_rates,
    pass_rate,
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
    offline: bool


async def run_eval(
    dataset_name: str,
    *,
    settings: Settings | None = None,
    run_name: str = "local",
    concurrency: int = 4,
    min_pass_rate: float | None = None,
    cases_dir: str | Path = DEFAULT_CASES_DIR,
    sync: bool = False,
) -> EvalRunSummary:
    resolved_settings = settings or load_settings()
    if concurrency <= 0:
        raise ValueError("concurrency must be greater than 0")
    if min_pass_rate is not None and not 0 <= min_pass_rate <= 1:
        raise ValueError("min_pass_rate must be between 0 and 1")

    offline = not resolved_settings.langfuse_enabled
    local_cases: tuple[EvalCase, ...] | None = None
    if offline or sync:
        local_cases = load_cases_from_yaml(cases_dir)

    langfuse = None
    if not offline:
        langfuse = create_langfuse_client(resolved_settings)
        if not langfuse_client_is_reachable(langfuse):
            close_langfuse_client(langfuse)
            langfuse = None
            offline = True
            print(
                "warning: Langfuse eval backend is configured but unreachable "
                f"(base_url={resolved_settings.langfuse_base_url}); auth_check failed. "
                "Falling back to OFFLINE mode."
            )
            if local_cases is None:
                local_cases = load_cases_from_yaml(cases_dir)

    if offline:
        missing = _missing_langfuse_settings(resolved_settings)
        if missing:
            print(
                "warning: Langfuse eval backend disabled; missing "
                + ", ".join(missing)
                + ". Running OFFLINE with local YAML cases and deterministic graders only."
            )
        result = await _run_local_eval(
            dataset_name=dataset_name,
            cases=local_cases or (),
            settings=resolved_settings,
            run_name=run_name,
            concurrency=concurrency,
        )
    else:
        assert langfuse is not None
        try:
            if sync:
                synced_count = await asyncio.to_thread(
                    sync_cases_to_langfuse,
                    local_cases or (),
                    dataset_name,
                    resolved_settings,
                    langfuse=langfuse,
                )
                print(f"synced {synced_count} eval cases to Langfuse dataset '{dataset_name}'.")
            result = await _run_langfuse_eval(
                dataset_name=dataset_name,
                langfuse=langfuse,
                settings=resolved_settings,
                run_name=run_name,
                concurrency=concurrency,
            )
        finally:
            close_langfuse_client(langfuse)

    print(result.format())
    overall = _run_evaluation_value(result, "pass_rate")
    exit_code = 0
    if min_pass_rate is not None and overall < min_pass_rate:
        print(f"eval gate failed: pass_rate {overall:.3f} is below threshold {min_pass_rate:.3f}.")
        exit_code = 1
    return EvalRunSummary(result=result, pass_rate=overall, exit_code=exit_code, offline=offline)


async def _run_langfuse_eval(
    *,
    dataset_name: str,
    langfuse: Any,
    settings: Settings,
    run_name: str,
    concurrency: int,
) -> ExperimentResult:
    runtime = await create_agent_runtime_async(settings=settings, attach_checkpointer=False)
    try:
        dataset = langfuse.get_dataset(dataset_name)
        if not dataset.items:
            raise ValueError(f"Langfuse dataset '{dataset_name}' has no items.")
        validate_dataset_schema(dataset.items)
        validate_expected_tool_names(dataset.items, _runtime_tool_names(runtime))
        task = _build_task(runtime, run_name=run_name)

        def execute_experiment() -> ExperimentResult:
            return dataset.run_experiment(
                name="ops_pilot eval",
                run_name=run_name,
                description="ops_pilot agent evaluation run",
                task=task,
                evaluators=build_item_evaluators(settings, include_judge=True),
                run_evaluators=[
                    pass_rate,
                    infrastructure_completion_rate,
                    conditional_task_pass_rate,
                    infrastructure_error_rates,
                    category_pass_rates,
                    run_performance_metrics,
                ],
                max_concurrency=concurrency,
                metadata=_run_metadata(runtime, dataset_name=dataset_name),
            )

        return await asyncio.to_thread(execute_experiment)
    finally:
        flush_tracing(runtime.tracing)
        await _close_runtime(runtime)


async def _run_local_eval(
    *,
    dataset_name: str,
    cases: Iterable[EvalCase],
    settings: Settings,
    run_name: str,
    concurrency: int,
) -> ExperimentResult:
    cases = tuple(cases)
    runtime = await create_agent_runtime_async(settings=settings, attach_checkpointer=False)
    try:
        validate_expected_tool_names(cases, _runtime_tool_names(runtime))
        task = _build_task(runtime, run_name=run_name)
        evaluators = build_item_evaluators(settings, include_judge=False)
        items = [case.to_experiment_item() for case in cases]
        semaphore = asyncio.Semaphore(concurrency)

        async def process_item(item: dict[str, Any]) -> ExperimentItemResult:
            async with semaphore:
                output = await task(item=item)
                evaluations = []
                for evaluator in evaluators:
                    evaluations.extend(
                        await _run_evaluator(
                            evaluator,
                            input=item.get("input"),
                            output=output,
                            expected_output=item.get("expected_output"),
                            metadata=item.get("metadata"),
                        )
                    )
                return ExperimentItemResult(
                    item=item,
                    output=output,
                    evaluations=evaluations,
                    trace_id=None,
                    dataset_run_id=None,
                )

        item_results = await asyncio.gather(*(process_item(item) for item in items))
        run_evaluations = []
        for run_evaluator in (
            pass_rate,
            infrastructure_completion_rate,
            conditional_task_pass_rate,
            infrastructure_error_rates,
            category_pass_rates,
            run_performance_metrics,
        ):
            run_evaluations.extend(await _run_evaluator(run_evaluator, item_results=list(item_results)))
        return ExperimentResult(
            name="ops_pilot eval",
            run_name=run_name,
            description=f"offline local eval for {dataset_name}",
            item_results=list(item_results),
            run_evaluations=run_evaluations,
            experiment_id=f"offline-{run_name}",
        )
    finally:
        flush_tracing(runtime.tracing)
        await _close_runtime(runtime)


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


async def _run_evaluator(evaluator: Any, **kwargs: Any) -> list[Any]:
    result = evaluator(**kwargs)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, list):
        return result
    return [result]


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


def _missing_langfuse_settings(settings: Settings) -> tuple[str, ...]:
    missing: list[str] = []
    if not settings.langfuse_public_key:
        missing.append("LANGFUSE_PUBLIC_KEY")
    if not settings.langfuse_secret_key:
        missing.append("LANGFUSE_SECRET_KEY")
    if not settings.langfuse_base_url:
        missing.append("LANGFUSE_BASE_URL")
    return tuple(missing)


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
