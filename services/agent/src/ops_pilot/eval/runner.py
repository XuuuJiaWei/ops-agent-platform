"""Eval runner for Langfuse-backed and local offline runs."""

from __future__ import annotations

import asyncio
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
)
from ops_pilot.eval.graders import build_item_evaluators, category_pass_rates, pass_rate
from ops_pilot.observability.langfuse import flush_tracing


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
    runtime = await create_agent_runtime_async(settings=settings, use_memory_checkpointer=False)
    try:
        dataset = langfuse.get_dataset(dataset_name)
        if not dataset.items:
            raise ValueError(f"Langfuse dataset '{dataset_name}' has no items.")
        task = _build_task(runtime, run_name=run_name)

        def execute_experiment() -> ExperimentResult:
            return dataset.run_experiment(
                name="ops_pilot eval",
                run_name=run_name,
                description="ops_pilot agent evaluation run",
                task=task,
                evaluators=build_item_evaluators(settings, include_judge=True),
                run_evaluators=[pass_rate, category_pass_rates],
                max_concurrency=concurrency,
                metadata={"runner": "ops_pilot.eval", "dataset_name": dataset_name},
            )

        return await asyncio.to_thread(execute_experiment)
    finally:
        flush_tracing(runtime.tracing)
        runtime.close()


async def _run_local_eval(
    *,
    dataset_name: str,
    cases: Iterable[EvalCase],
    settings: Settings,
    run_name: str,
    concurrency: int,
) -> ExperimentResult:
    runtime = await create_agent_runtime_async(settings=settings, use_memory_checkpointer=False)
    try:
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
        for run_evaluator in (pass_rate, category_pass_rates):
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
        runtime.close()


def _build_task(runtime: Any, *, run_name: str) -> Any:
    async def task(*, item: Any, **_: Any) -> dict[str, Any]:
        input_text = _item_input(item)
        metadata = _item_metadata(item)
        case_id = _case_id(item, metadata=metadata, input_text=input_text)
        timeout_s = _timeout_s(metadata)
        started = time.perf_counter()
        try:
            trace = await asyncio.wait_for(
                runtime.ainvoke_trace(
                    input_text,
                    protocol="eval",
                    thread_id=f"eval-{case_id}",
                    run_id=f"{run_name}:{case_id}",
                    extra_metadata={
                        "eval_case_id": case_id,
                        "eval_category": metadata.get("category"),
                        "eval_run_name": run_name,
                    },
                ),
                timeout=timeout_s,
            )
            return trace.as_output()
        except Exception as exc:  # noqa: BLE001 - task errors are scored by no_error.
            latency_s = time.perf_counter() - started
            return {
                "final_text": "",
                "tool_calls": [],
                "steps": 0,
                "latency_s": latency_s,
                "error": str(exc) or type(exc).__name__,
                "error_type": type(exc).__name__,
                "recursion_limit_hit": _is_recursion_limit_exception(exc),
            }

    return task


async def _run_evaluator(evaluator: Any, **kwargs: Any) -> list[Any]:
    result = evaluator(**kwargs)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, list):
        return result
    return [result]


def _item_input(item: Any) -> str:
    value = item.get("input") if isinstance(item, Mapping) else getattr(item, "input", None)
    if value is None:
        raise ValueError("Eval item is missing input.")
    return str(value)


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
