"""Transactional chaos control for the Astronomy Shop flagd feature flags.

The Astronomy Shop injects faults via feature flags served by flagd. The flags
live in a Kubernetes ConfigMap (``flagd-config`` in namespace
``astronomy-shop``) whose single data key ``demo.flagd.json`` holds a JSON
string of the form::

    {"flags": {"paymentFailure": {"defaultVariant": "off", "variants": {...}}, ...}}

This module patches one flag transactionally, polls flagd's OFREP data plane
until the new variant is stable, runs the bound eval case, restores the exact
original flag specification, and polls recovery. It therefore follows the same
condition-based readiness pattern as the OpenTelemetry Demo telemetry tests
instead of guessing ConfigMap propagation time with fixed sleeps.
"""

from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ops_pilot.config.settings import Settings

NAMESPACE = "astronomy-shop"
CONFIGMAP = "flagd-config"
DATA_KEY = "demo.flagd.json"
FLAGD_OFREP_SERVICE_PROXY = f"/api/v1/namespaces/{NAMESPACE}/services/http:flagd:8016/proxy/ofrep/v1/evaluate/flags"

# The 13 fault-injection flags. loadGeneratorTraffic / loadGeneratorVUs are the
# demo's normal load-generator controls (traffic must stay ON to produce signals)
# and are deliberately excluded — reset_all must never touch them.
FAULT_FLAGS: frozenset[str] = frozenset(
    {
        "paymentFailure",
        "paymentUnreachable",
        "productCatalogFailure",
        "cartFailure",
        "adFailure",
        "adHighCpu",
        "adManualGc",
        "emailMemoryLeak",
        "failedReadinessProbe",
        "imageSlowLoad",
        "intlShippingSlowdown",
        "kafkaQueueProblems",
        "recommendationCacheFailure",
    }
)

OFF_VARIANT = "off"


class ChaosError(RuntimeError):
    """Raised when a flag-control operation against the cluster fails."""


def _kubeconfig_from_settings(settings: Settings) -> str:
    """Resolve the kubeconfig path from the kubernetes MCP server config."""

    for server in settings.mcp.servers:
        if server.name != "kubernetes":
            continue
        env_path = server.env.get("KUBECONFIG")
        if env_path:
            return env_path
        args = list(server.args)
        for index, arg in enumerate(args):
            if arg == "--kubeconfig" and index + 1 < len(args):
                return args[index + 1]
        raise ChaosError(
            "kubernetes MCP server is configured but has no KUBECONFIG env or "
            "--kubeconfig arg; cannot drive kubectl for chaos flag control."
        )
    raise ChaosError(
        "no 'kubernetes' MCP server found in config; chaos flag control needs a "
        "kubeconfig. Add the kubernetes server to config/config.yaml."
    )


def _kubectl(
    settings: Settings,
    *args: str,
    input_text: str | None = None,
    timeout_seconds: float | None = None,
) -> str:
    """Run a kubectl command scoped to the astronomy-shop namespace and return stdout."""

    kubeconfig = _kubeconfig_from_settings(settings)
    command = ["kubectl", "--kubeconfig", kubeconfig, "-n", NAMESPACE, *args]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell.
            command,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=timeout_seconds or settings.chaos_flag_sync_timeout_seconds,
            check=True,
        )
    except FileNotFoundError as exc:
        raise ChaosError("kubectl not found on PATH; install kubectl to use chaos flag control.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise ChaosError(f"kubectl {' '.join(args)} failed (exit {exc.returncode}): {stderr}") from exc
    except subprocess.TimeoutExpired as exc:
        timeout = timeout_seconds or settings.chaos_flag_sync_timeout_seconds
        raise ChaosError(f"kubectl {' '.join(args)} timed out after {timeout:g}s") from exc
    return completed.stdout


def read_flags(settings: Settings) -> dict:
    """Read and parse the full flagd flags document from the ConfigMap."""

    raw = _kubectl(
        settings,
        "get",
        "configmap",
        CONFIGMAP,
        "-o",
        r"jsonpath={.data.demo\.flagd\.json}",
    )
    if not raw.strip():
        raise ChaosError(f"ConfigMap '{CONFIGMAP}' has no '{DATA_KEY}' data key or it is empty.")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChaosError(f"'{DATA_KEY}' in ConfigMap '{CONFIGMAP}' is not valid JSON: {exc}") from exc
    if not isinstance(document, Mapping) or "flags" not in document:
        raise ChaosError(f"'{DATA_KEY}' does not contain a 'flags' object.")
    return dict(document)


def current_variants(settings: Settings) -> dict[str, str]:
    """Return ``{flag: defaultVariant}`` for every flag in the ConfigMap."""

    document = read_flags(settings)
    flags = document.get("flags", {})
    return {name: str(spec.get("defaultVariant", "")) for name, spec in flags.items()}


def _patch_document(settings: Settings, document: Mapping) -> None:
    """Write a mutated flags document back to the ConfigMap via merge patch."""

    mutated = json.dumps(document)
    patch = json.dumps({"data": {DATA_KEY: mutated}})
    _kubectl(settings, "patch", "configmap", CONFIGMAP, "--type", "merge", "-p", patch)


def set_flag(
    settings: Settings,
    flag: str,
    variant: str,
    *,
    target: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Activate one variant and return the exact prior flag specification.

    A plain injection removes any existing targeting so ``defaultVariant`` is
    authoritative. A targeted injection replaces targeting for the duration of
    the lease. This is required for ``productCatalogFailure``: the upstream demo
    document currently targets both branches to ``off``, so changing only the
    default variant does not enable the fault.
    """

    document = read_flags(settings)
    flags = document["flags"]
    if flag not in flags:
        raise ChaosError(f"unknown flag '{flag}'; not present in {CONFIGMAP}.")
    variants = flags[flag].get("variants", {})
    if variant not in variants:
        available = ", ".join(sorted(str(key) for key in variants)) or "(none)"
        raise ChaosError(f"flag '{flag}' has no variant '{variant}'. Available: {available}.")
    original = copy.deepcopy(flags[flag])
    flags[flag]["defaultVariant"] = variant
    if target:
        flags[flag]["targeting"] = _targeting_rule(target, variant)
    else:
        flags[flag].pop("targeting", None)
    _patch_document(settings, document)
    return original


def restore_flag(settings: Settings, flag: str, original: Mapping[str, Any]) -> None:
    """Restore the exact flag specification captured before injection."""

    document = read_flags(settings)
    flags = document["flags"]
    if flag not in flags:
        raise ChaosError(f"unknown flag '{flag}'; not present in {CONFIGMAP}.")
    flags[flag] = copy.deepcopy(dict(original))
    _patch_document(settings, document)


def evaluate_flag(
    settings: Settings,
    flag: str,
    *,
    context: Mapping[str, Any] | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Evaluate a flag through flagd's OFREP service via the Kubernetes API."""

    raw = _kubectl(
        settings,
        "create",
        "--raw",
        f"{FLAGD_OFREP_SERVICE_PROXY}/{flag}",
        "-f",
        "-",
        input_text=json.dumps({"context": dict(context or {})}),
        timeout_seconds=timeout_seconds,
    )
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChaosError(f"flagd returned invalid OFREP JSON for '{flag}': {exc}") from exc
    if not isinstance(result, Mapping) or not result.get("variant"):
        raise ChaosError(f"flagd returned an invalid OFREP evaluation for '{flag}': {result!r}")
    return dict(result)


async def wait_for_flag_variant(
    settings: Settings,
    flag: str,
    variant: str,
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Poll OFREP until ``variant`` is observed for consecutive stable reads."""

    started = time.monotonic()
    deadline = started + settings.chaos_flag_sync_timeout_seconds
    consecutive = 0
    attempts = 0
    last_result: dict[str, Any] | None = None
    last_error: Exception | None = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            detail = str(last_error) if last_error is not None else f"last evaluation={last_result!r}"
            raise ChaosError(
                f"flagd did not report {flag}={variant!r} for {settings.chaos_stable_reads} stable reads "
                f"within {settings.chaos_flag_sync_timeout_seconds:g}s; {detail}"
            )
        attempts += 1
        try:
            last_result = await asyncio.to_thread(
                evaluate_flag,
                settings,
                flag,
                context=context,
                timeout_seconds=remaining,
            )
            last_error = None
            if last_result.get("variant") == variant:
                consecutive += 1
                if consecutive >= settings.chaos_stable_reads:
                    return {
                        "attempts": attempts,
                        "elapsed_s": time.monotonic() - started,
                        "evaluation": last_result,
                    }
            else:
                consecutive = 0
        except Exception as exc:  # noqa: BLE001 - transient probe errors are retried until the deadline.
            last_error = exc
            consecutive = 0

        remaining = deadline - time.monotonic()
        await asyncio.sleep(min(settings.chaos_poll_interval_seconds, remaining))


def _targeting_rule(target: Mapping[str, Any], variant: str) -> dict[str, Any]:
    conditions = [{"==": [{"var": key}, value]} for key, value in target.items()]
    condition: dict[str, Any] = conditions[0] if len(conditions) == 1 else {"and": conditions}
    return {"if": [condition, variant, OFF_VARIANT]}


def reset_all(settings: Settings) -> dict[str, str]:
    """Set every present fault flag to ``off`` in one patch; leave load-gen alone.

    Idempotent. Serves both as the standalone ``chaos reset`` and as the crash
    safety net at the end of an orchestrated run. Returns the resulting variants.
    """

    document = read_flags(settings)
    flags = document["flags"]
    changed = False
    for flag in FAULT_FLAGS:
        spec = flags.get(flag)
        if spec is None:
            continue
        if spec.get("defaultVariant") != OFF_VARIANT:
            spec["defaultVariant"] = OFF_VARIANT
            changed = True
    if changed:
        _patch_document(settings, document)
    return {name: str(spec.get("defaultVariant", "")) for name, spec in flags.items()}


async def run_chaos_eval(
    *,
    settings: Settings,
    dataset_name: str = "otel_scenarios",
    only: list[str] | None = None,
    cases_dir: str | Path,
    run_name: str | None = None,
) -> int:
    """Drive the full chaos->eval loop ONLINE and record to a Langfuse dataset run.

    For every inject-bearing case: reset all fault flags -> verify baseline through
    OFREP -> enable that case's ONE flag -> verify injection through OFREP -> invoke
    the agent (traced) -> restore the original flag spec -> verify recovery. The
    whole thing is a single serial
    ``langfuse.run_experiment`` call so all cases land in ONE dataset run for UI
    comparison. A ``finally`` block ALWAYS resets every fault flag so a crash or
    Ctrl-C never leaves the cluster dirty.
    """

    # Imported here (not at module top) to keep the flag-control helpers importable
    # without pulling in the agent runtime / langfuse eval stack.
    from ops_pilot.agent.factory import create_agent_runtime_async
    from ops_pilot.eval.dataset import (
        close_langfuse_client,
        create_langfuse_client,
        langfuse_client_is_reachable,
        load_cases_from_yaml,
        validate_dataset_schema,
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
    from ops_pilot.eval.runner import _build_task, _close_runtime, _run_evaluation_value
    from ops_pilot.observability.langfuse import finish_observation, flush_tracing, observation

    resolved_cases_dir = cases_dir

    # 1. LOCAL yaml is authoritative for flag/variant/target.
    inject_by_id = {case.id: case.inject for case in load_cases_from_yaml(resolved_cases_dir) if case.inject}
    if only:
        wanted = set(only)
        inject_by_id = {case_id: inject for case_id, inject in inject_by_id.items() if case_id in wanted}
        missing_ids = wanted - set(inject_by_id)
        if missing_ids:
            print(f"error: --only ids have no inject in {resolved_cases_dir}: {', '.join(sorted(missing_ids))}")
            return 1
    if not inject_by_id:
        print("no inject-bearing cases matched; nothing to run.")
        return 0

    # 2. Online is REQUIRED — recording the run is the whole point.
    if not settings.langfuse_enabled:
        print(
            "error: chaos run records to Langfuse and needs it configured. Set "
            "LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and langfuse.base_url."
        )
        return 1
    langfuse = create_langfuse_client(settings)
    if not langfuse_client_is_reachable(langfuse):
        close_langfuse_client(langfuse)
        print(
            f"error: Langfuse is unreachable at {settings.langfuse_base_url} (auth_check failed). "
            "chaos run requires an online backend to record the dataset run."
        )
        return 1

    # 3. Pull the matching DatasetItems so the run links to the dataset.
    dataset = langfuse.get_dataset(dataset_name)
    items = [item for item in dataset.items if item.id in inject_by_id]
    missing = set(inject_by_id) - {item.id for item in items}
    if missing:
        close_langfuse_client(langfuse)
        print(
            f"error: dataset '{dataset_name}' is missing items {', '.join(sorted(missing))}. "
            "Re-run `ops_pilot eval sync --dataset-name "
            f"{dataset_name}` so the inject-bearing cases exist online."
        )
        return 1
    try:
        validate_dataset_schema(items)
    except Exception as exc:
        close_langfuse_client(langfuse)
        print(f"error: {exc}")
        return 1

    runtime = await create_agent_runtime_async(settings=settings, attach_checkpointer=False, bypass_hitl=True)
    base_task = _build_task(runtime, run_name=run_name or "chaos")

    async def chaos_task(*, item, **_):
        inject = inject_by_id[item.id]
        trace_metadata = {
            "eval_case_id": item.id,
            "fault_flag": inject.flag,
            "fault_variant": inject.variant,
            "fault_target": dict(inject.target or {}),
        }
        with observation(
            runtime.tracing,
            name="execute-chaos-case",
            input={"case_id": item.id},
            metadata=trace_metadata,
        ) as current:
            original: dict[str, Any] | None = None
            output: dict[str, Any] | None = None
            try:
                with observation(
                    runtime.tracing,
                    name="prepare-fault",
                    metadata=trace_metadata,
                ) as phase:
                    await asyncio.to_thread(reset_all, settings)
                    baseline = await wait_for_flag_variant(
                        settings,
                        inject.flag,
                        OFF_VARIANT,
                        context=inject.target,
                    )
                    finish_observation(phase, output=baseline)

                with observation(
                    runtime.tracing,
                    name="inject-fault",
                    metadata=trace_metadata,
                ) as phase:
                    original = await asyncio.to_thread(
                        set_flag,
                        settings,
                        inject.flag,
                        inject.variant,
                        target=inject.target,
                    )
                    ready = await wait_for_flag_variant(
                        settings,
                        inject.flag,
                        inject.variant,
                        context=inject.target,
                    )
                    finish_observation(phase, output=ready)
                    print(
                        f"[chaos] {item.id}: {inject.flag}={inject.variant} ready "
                        f"after {ready['elapsed_s']:.1f}s/{ready['attempts']} probes"
                    )

                task_output = await base_task(item=item)
                if not isinstance(task_output, dict):
                    raise TypeError(f"Chaos eval task returned {type(task_output).__name__}, expected dict.")
                output = task_output
                task_error = output.get("error")
                finish_observation(
                    current,
                    output=output.get("final_text") or output,
                    error=RuntimeError(str(task_error)) if task_error else None,
                    metadata={"agent_latency_seconds": output.get("latency_s")},
                )
                return output
            except Exception as exc:
                finish_observation(current, output=output, error=exc)
                raise
            finally:
                if original is not None:
                    with observation(
                        runtime.tracing,
                        name="recover-fault",
                        metadata=trace_metadata,
                    ) as phase:
                        try:
                            await asyncio.to_thread(restore_flag, settings, inject.flag, original)
                            recovered = await wait_for_flag_variant(
                                settings,
                                inject.flag,
                                OFF_VARIANT,
                                context=inject.target,
                            )
                            finish_observation(phase, output=recovered)
                            print(
                                f"[chaos] {item.id}: {inject.flag} recovered "
                                f"after {recovered['elapsed_s']:.1f}s/{recovered['attempts']} probes"
                            )
                        except Exception as exc:
                            finish_observation(phase, error=exc)
                            raise

    def execute_experiment():
        return langfuse.run_experiment(
            name="ops_pilot chaos eval",
            run_name=run_name,
            description="chaos->eval: one injected flag per case, flag = ground truth",
            data=items,
            task=chaos_task,
            evaluators=build_item_evaluators(settings, include_judge=True),
            run_evaluators=[
                pass_rate,
                infrastructure_completion_rate,
                conditional_task_pass_rate,
                infrastructure_error_rates,
                category_pass_rates,
                run_performance_metrics,
            ],
            max_concurrency=1,
            metadata={
                "runner": "ops_pilot.chaos",
                "dataset_name": dataset_name,
                "flag_sync_timeout_seconds": settings.chaos_flag_sync_timeout_seconds,
                "flag_poll_interval_seconds": settings.chaos_poll_interval_seconds,
                "flag_stable_reads": settings.chaos_stable_reads,
            },
        )

    try:
        result = await asyncio.to_thread(execute_experiment)
    finally:
        try:
            await asyncio.to_thread(reset_all, settings)
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask the original error.
            print(f"WARNING: failed to reset fault flags after chaos run: {exc}")
        flush_tracing(runtime.tracing)
        try:
            await _close_runtime(runtime)
        finally:
            close_langfuse_client(langfuse)

    print(result.format())
    overall = _run_evaluation_value(result, "pass_rate")
    return 0 if overall >= 1.0 else 1
