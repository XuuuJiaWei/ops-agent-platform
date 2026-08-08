"""Chaos injection control for the OTel-demo flagd feature flags.

The OTel demo injects faults via feature flags served by flagd. The flags live
in a Kubernetes ConfigMap (``flagd-config`` in namespace ``otel-demo``) whose
single data key ``demo.flagd.json`` holds a JSON string of the form::

    {"flags": {"paymentFailure": {"defaultVariant": "off", "variants": {...}}, ...}}

Turning a fault on/off = mutating that flag's ``defaultVariant`` and patching the
ConfigMap. flagd hot-reloads the mounted file within ~30-60s.

This module drives those flags via ``kubectl`` (reusing the kubeconfig already
configured for the kubernetes MCP server) so the chaos->eval loop can enable a
single fault, let signals settle, run the bound eval case, and reset — and always
reset every fault flag afterward so the cluster never stays dirty.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

from ops_pilot.config.settings import Settings

NAMESPACE = "otel-demo"
CONFIGMAP = "flagd-config"
DATA_KEY = "demo.flagd.json"

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


def _kubectl(settings: Settings, *args: str) -> str:
    """Run a kubectl command scoped to the otel-demo namespace and return stdout."""

    kubeconfig = _kubeconfig_from_settings(settings)
    command = ["kubectl", "--kubeconfig", kubeconfig, "-n", NAMESPACE, *args]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell.
            command,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise ChaosError("kubectl not found on PATH; install kubectl to use chaos flag control.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise ChaosError(f"kubectl {' '.join(args)} failed (exit {exc.returncode}): {stderr}") from exc
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
    return document


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


def set_flag(settings: Settings, flag: str, variant: str) -> None:
    """Set a single flag's defaultVariant and patch the ConfigMap."""

    document = read_flags(settings)
    flags = document["flags"]
    if flag not in flags:
        raise ChaosError(f"unknown flag '{flag}'; not present in {CONFIGMAP}.")
    variants = flags[flag].get("variants", {})
    if variant not in variants:
        available = ", ".join(sorted(str(key) for key in variants)) or "(none)"
        raise ChaosError(f"flag '{flag}' has no variant '{variant}'. Available: {available}.")
    flags[flag]["defaultVariant"] = variant
    _patch_document(settings, document)


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
    cases_dir: str | Path | None = None,
    run_name: str | None = None,
) -> int:
    """Drive the full chaos->eval loop ONLINE and record to a Langfuse dataset run.

    For every inject-bearing case: reset all fault flags -> enable that case's ONE
    flag -> wait ``settle_s`` for signals -> invoke the agent (traced) -> disable the
    flag -> cooldown -> next. The whole thing is a single serial
    ``langfuse.run_experiment`` call so all cases land in ONE dataset run for UI
    comparison. A ``finally`` block ALWAYS resets every fault flag so a crash or
    Ctrl-C never leaves the cluster dirty.
    """

    # Imported here (not at module top) to keep the flag-control helpers importable
    # without pulling in the agent runtime / langfuse eval stack.
    from ops_pilot.agent.factory import create_agent_runtime_async
    from ops_pilot.eval.dataset import (
        DEFAULT_CASES_DIR,
        close_langfuse_client,
        create_langfuse_client,
        langfuse_client_is_reachable,
        load_cases_from_yaml,
    )
    from ops_pilot.eval.graders import build_item_evaluators, category_pass_rates, pass_rate
    from ops_pilot.eval.runner import _build_task, _close_runtime, _run_evaluation_value
    from ops_pilot.observability.langfuse import flush_tracing

    resolved_cases_dir = cases_dir if cases_dir is not None else DEFAULT_CASES_DIR

    # 1. LOCAL yaml is authoritative for flag/variant/settle_s/cooldown_s.
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

    runtime = await create_agent_runtime_async(settings=settings, use_memory_checkpointer=False)
    base_task = _build_task(runtime, run_name=run_name or "chaos")

    async def chaos_task(*, item, **_):
        inject = inject_by_id[item.id]
        reset_all(settings)
        set_flag(settings, inject.flag, inject.variant)
        print(f"[chaos] {item.id}: {inject.flag}={inject.variant}; settling {inject.settle_s:.0f}s...")
        try:
            await asyncio.sleep(inject.settle_s)
            return await base_task(item=item)
        finally:
            set_flag(settings, inject.flag, OFF_VARIANT)
            await asyncio.sleep(inject.cooldown_s)

    def execute_experiment():
        return langfuse.run_experiment(
            name="ops_pilot chaos eval",
            run_name=run_name,
            description="chaos->eval: one injected flag per case, flag = ground truth",
            data=items,
            task=chaos_task,
            evaluators=build_item_evaluators(settings, include_judge=True),
            run_evaluators=[pass_rate, category_pass_rates],
            max_concurrency=1,
            metadata={"runner": "ops_pilot.chaos", "dataset_name": dataset_name},
        )

    try:
        result = await asyncio.to_thread(execute_experiment)
    finally:
        try:
            reset_all(settings)
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
