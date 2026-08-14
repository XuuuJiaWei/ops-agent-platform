"""Serial flagd chaos experiments against the OpenTelemetry Demo."""

from __future__ import annotations

import asyncio
import copy
import os
import socket
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from ops_pilot.config.settings import Settings

if TYPE_CHECKING:
    from ops_pilot.eval.dataset import EvalCase, InjectSpec


# Runtime fault flags from the OpenTelemetry Demo. Load-generator controls are
# deliberately excluded: chaos needs traffic enabled to produce telemetry.
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
    """Raised when the live flagd experiment cannot be proven safe."""


class FlagdAPI(Protocol):
    settings: Settings

    async def read(self) -> dict[str, Any]: ...

    async def write(self, document: Mapping[str, Any]) -> None: ...

    async def evaluate(self, flag: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]: ...


class FlagdClient:
    """One bounded kubectl port-forward for flagd-ui and OFREP."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ui_port = _reserve_local_port()
        self.ofrep_port = _reserve_local_port()
        self.process: asyncio.subprocess.Process | None = None
        self.http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> FlagdClient:
        command = [
            "kubectl",
            "--kubeconfig",
            _kubeconfig_from_settings(self.settings),
            "-n",
            self.settings.chaos_namespace,
            "port-forward",
            f"service/{self.settings.chaos_flagd_service}",
            f"{self.ui_port}:{self.settings.chaos_flagd_ui_port}",
            f"{self.ofrep_port}:{self.settings.chaos_flagd_service_port}",
            "--address",
            "127.0.0.1",
        ]
        kwargs: dict[str, Any] = {
            "stdout": asyncio.subprocess.DEVNULL,
            "stderr": asyncio.subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.process = await asyncio.create_subprocess_exec(*command, **kwargs)
        except FileNotFoundError as exc:
            raise ChaosError("kubectl not found on PATH; install kubectl to use chaos control.") from exc

        self.http = httpx.AsyncClient(timeout=5.0)
        try:
            await self._wait_until_ready()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self.http is not None:
            await self.http.aclose()
            self.http = None
        process = self.process
        self.process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def read(self) -> dict[str, Any]:
        return _parse_document(await self._request("ui", "/api/read"), source="flagd-ui /api/read")

    async def write(self, document: Mapping[str, Any]) -> None:
        await self._request("ui", "/api/write", method="POST", json={"data": document})

    async def evaluate(self, flag: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        result = await self._request(
            "ofrep",
            f"/ofrep/v1/evaluate/flags/{flag}",
            method="POST",
            json={"context": dict(context or {})},
        )
        if not isinstance(result, Mapping) or not result.get("variant"):
            raise ChaosError(f"flagd returned an invalid OFREP evaluation for '{flag}': {result!r}")
        return dict(result)

    async def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.settings.chaos_flag_sync_timeout_seconds
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            if self.process is not None and self.process.returncode is not None:
                raise ChaosError(f"kubectl port-forward exited with code {self.process.returncode}")
            try:
                await self.read()
                return
            except (httpx.HTTPError, ChaosError) as exc:
                last_error = exc
                await asyncio.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
        raise ChaosError(
            f"flagd port-forward was not ready within {self.settings.chaos_flag_sync_timeout_seconds:g}s: {last_error}"
        )

    async def _request(
        self,
        endpoint: str,
        path: str,
        *,
        method: str = "GET",
        json: Mapping[str, Any] | None = None,
    ) -> Any:
        if self.http is None:
            raise ChaosError("flagd client is not open")
        port = self.ui_port if endpoint == "ui" else self.ofrep_port
        try:
            response = await self.http.request(method, f"http://127.0.0.1:{port}{path}", json=json)
            response.raise_for_status()
            return response.json() if response.content else None
        except httpx.HTTPStatusError as exc:
            detail = f"flagd {method} {path} returned HTTP {exc.response.status_code}: {exc.response.text}"
            raise ChaosError(detail) from exc


async def current_variants(settings: Settings) -> dict[str, str]:
    async with FlagdClient(settings) as flagd:
        return _variants(await flagd.read())


async def set_flag(
    settings: Settings,
    flag: str,
    variant: str,
    *,
    target: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Set one live flag through the official flagd-ui API and verify OFREP."""

    async with FlagdClient(settings) as flagd:
        current = await flagd.read()
        desired, original = _document_with_flag(current, flag, variant, target=target)
        await flagd.write(desired)
        await wait_for_document(flagd, desired)
        await wait_for_flag_variant(flagd, flag, variant, context=target)
        return original


async def reset_all(settings: Settings) -> dict[str, str]:
    """Set every fault flag to a clean off baseline without changing Helm state."""

    async with FlagdClient(settings) as flagd:
        desired = _baseline_document(await flagd.read())
        await flagd.write(desired)
        await wait_for_document(flagd, desired)
        await _wait_for_baseline(flagd)
        return _variants(desired)


def _document_with_flag(
    document: Mapping[str, Any],
    flag: str,
    variant: str,
    *,
    target: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    desired = copy.deepcopy(dict(document))
    flags = desired.get("flags")
    if not isinstance(flags, dict) or flag not in flags:
        raise ChaosError(f"unknown flag '{flag}'; not present in the live flagd document.")
    spec = flags[flag]
    variants = spec.get("variants", {}) if isinstance(spec, dict) else {}
    if variant not in variants:
        available = ", ".join(sorted(str(key) for key in variants)) or "(none)"
        raise ChaosError(f"flag '{flag}' has no variant '{variant}'. Available: {available}.")
    original = copy.deepcopy(spec)
    spec["defaultVariant"] = variant
    if target:
        spec["targeting"] = _targeting_rule(target, variant)
    else:
        spec.pop("targeting", None)
    return desired, original


def _baseline_document(document: Mapping[str, Any]) -> dict[str, Any]:
    desired = copy.deepcopy(dict(document))
    flags = desired.get("flags")
    if not isinstance(flags, dict):
        raise ChaosError("flagd document has no valid 'flags' mapping.")
    for flag in FAULT_FLAGS:
        spec = flags.get(flag)
        if isinstance(spec, dict):
            spec["defaultVariant"] = OFF_VARIANT
            spec.pop("targeting", None)
    return desired


async def wait_for_document(flagd: FlagdAPI, expected: Mapping[str, Any]) -> dict[str, Any]:
    deadline = time.monotonic() + flagd.settings.chaos_flag_sync_timeout_seconds
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = await flagd.read()
        if _same_flag_state(last, expected):
            return last
        await asyncio.sleep(flagd.settings.chaos_poll_interval_seconds)
    raise ChaosError(f"flagd-ui did not expose the expected document before the deadline; last={last!r}")


async def wait_for_flag_variant(
    flagd: FlagdAPI,
    flag: str,
    variant: str,
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Require consecutive OFREP reads before declaring the environment ready."""

    settings = flagd.settings
    started = time.monotonic()
    deadline = started + settings.chaos_flag_sync_timeout_seconds
    stable = 0
    attempts = 0
    last: dict[str, Any] | None = None
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        attempts += 1
        try:
            last = await flagd.evaluate(flag, context)
            last_error = None
            stable = stable + 1 if last.get("variant") == variant else 0
            if stable >= settings.chaos_stable_reads:
                return {
                    "attempts": attempts,
                    "elapsed_s": time.monotonic() - started,
                    "evaluation": last,
                }
        except (httpx.HTTPError, ChaosError) as exc:
            stable = 0
            last_error = exc
        await asyncio.sleep(min(settings.chaos_poll_interval_seconds, max(0.0, deadline - time.monotonic())))
    detail = last_error or f"last evaluation={last!r}"
    raise ChaosError(
        f"flagd did not report {flag}={variant!r} for {settings.chaos_stable_reads} stable reads "
        f"within {settings.chaos_flag_sync_timeout_seconds:g}s; {detail}"
    )


async def _wait_for_baseline(flagd: FlagdAPI) -> None:
    await asyncio.gather(*(wait_for_flag_variant(flagd, flag, OFF_VARIANT) for flag in sorted(FAULT_FLAGS)))


def validate_flag_catalog(document: Mapping[str, Any], cases: Mapping[str, InjectSpec]) -> None:
    """Fail before mutation when local injections do not match the live catalog."""

    flags = document.get("flags")
    if not isinstance(flags, Mapping):
        raise ChaosError("flagd document has no valid 'flags' mapping.")
    missing_flags = sorted(FAULT_FLAGS - set(flags))
    if missing_flags:
        raise ChaosError("live flagd catalog is missing fault flags: " + ", ".join(missing_flags))
    traffic = flags.get("loadGeneratorTraffic")
    if not isinstance(traffic, Mapping) or traffic.get("defaultVariant") != "on":
        raise ChaosError("loadGeneratorTraffic must be present and set to 'on' so faults produce telemetry.")
    problems: list[str] = []
    for case_id, inject in cases.items():
        spec = flags.get(inject.flag)
        variants = spec.get("variants", {}) if isinstance(spec, Mapping) else {}
        if inject.variant not in variants:
            problems.append(f"{case_id}: {inject.flag} has no variant {inject.variant!r}")
    if problems:
        raise ChaosError("local chaos cases do not match the live flag catalog: " + "; ".join(problems))


def validate_mcp_runtime(settings: Settings, runtime: Any, cases: Sequence[EvalCase]) -> tuple[str, ...]:
    """Require every configured MCP server and every case tool before mutation."""

    from ops_pilot.eval.dataset import validate_expected_tool_names

    configured = tuple(server.name for server in settings.mcp.servers)
    optional = [server.name for server in settings.mcp.servers if not server.required]
    if optional:
        raise ChaosError("all MCP servers must set required: true for chaos: " + ", ".join(optional))
    statuses = {status.name: status for status in runtime.mcp.status.servers}
    missing = [name for name in configured if name not in statuses]
    failed = [name for name in configured if name in statuses and not statuses[name].ok]
    empty = [name for name in configured if name in statuses and statuses[name].tool_count <= 0]
    if missing or failed or empty:
        details = []
        if missing:
            details.append("not loaded=" + ", ".join(missing))
        if failed:
            details.append("failed=" + ", ".join(failed))
        if empty:
            details.append("zero tools=" + ", ".join(empty))
        raise ChaosError("MCP preflight failed: " + "; ".join(details))
    validate_expected_tool_names(cases, runtime.mcp.tool_names)
    return configured


async def run_chaos_eval(
    *,
    settings: Settings,
    dataset_name: str = "otel_scenarios",
    only: list[str] | None = None,
    cases_dir: str | Path,
    run_name: str | None = None,
) -> int:
    """Sync local cases, load all MCPs, then run one fully restored flag lease per case."""

    from ops_pilot.agent.factory import create_agent_runtime_async
    from ops_pilot.eval.dataset import (
        close_langfuse_client,
        create_langfuse_client,
        langfuse_client_is_reachable,
        load_cases_from_yaml,
        sync_and_verify_cases_to_langfuse,
    )
    from ops_pilot.eval.graders import (
        build_item_evaluators,
        category_pass_rates,
        conditional_task_pass_rate,
        hitl_safety_rate,
        infrastructure_completion_rate,
        infrastructure_error_rates,
        pass_rate,
        run_performance_metrics,
    )
    from ops_pilot.eval.runner import _build_task, _close_runtime, _run_evaluation_value

    local_cases = tuple(case for case in load_cases_from_yaml(cases_dir) if case.inject)
    selected_cases = local_cases
    if only:
        wanted = set(only)
        selected_cases = tuple(case for case in local_cases if case.id in wanted)
        missing = wanted - {case.id for case in selected_cases}
        if missing:
            print(f"error: --only ids have no inject in {cases_dir}: {', '.join(sorted(missing))}")
            return 1
    if not selected_cases:
        print("no inject-bearing cases matched; nothing to run.")
        return 0
    if not settings.langfuse_enabled:
        print("error: chaos run requires Langfuse credentials and langfuse.base_url.")
        return 1

    inject_by_id: dict[str, InjectSpec] = {case.id: case.inject for case in selected_cases if case.inject is not None}
    langfuse = create_langfuse_client(settings)
    runtime: Any | None = None
    result: Any | None = None
    run_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    try:
        if not langfuse_client_is_reachable(langfuse):
            raise ChaosError(f"Langfuse is unreachable at {settings.langfuse_base_url} (auth_check failed).")
        print(f"[chaos] syncing {len(local_cases)} local cases to Langfuse", flush=True)
        online_items = await asyncio.to_thread(
            sync_and_verify_cases_to_langfuse,
            local_cases,
            dataset_name,
            settings,
            langfuse=langfuse,
        )
        online_by_id = {str(item.id): item for item in online_items}
        items = [online_by_id[case.id] for case in selected_cases]

        print("[chaos] loading all configured MCP servers", flush=True)
        runtime = await create_agent_runtime_async(
            settings=replace(settings, persistence_backend="memory", persistence_database_url=None),
            attach_checkpointer=False,
            bypass_hitl=True,
        )
        servers = validate_mcp_runtime(settings, runtime, selected_cases)
        print(f"[chaos] MCP preflight passed: {len(servers)} servers, {len(runtime.mcp.tools)} tools", flush=True)

        async with FlagdClient(settings) as flagd:
            validate_flag_catalog(await flagd.read(), inject_by_id)
        print("[chaos] live flagd catalog preflight passed", flush=True)
        base_task = _build_task(runtime, run_name=run_name or "chaos")

        async def chaos_task(*, item: Any, **_: Any) -> dict[str, Any]:
            inject = inject_by_id[str(item.id)]
            # Langfuse owns this task's event loop, so it must also own every
            # loop-bound resource used by the task.
            async with FlagdClient(settings) as flagd:
                original = await flagd.read()
                validate_flag_catalog(original, {str(item.id): inject})
                original_variant = str((await flagd.evaluate(inject.flag, inject.target))["variant"])
                baseline = _baseline_document(original)
                try:
                    await flagd.write(baseline)
                    await wait_for_document(flagd, baseline)
                    await _wait_for_baseline(flagd)
                    desired, _ = _document_with_flag(
                        baseline,
                        inject.flag,
                        inject.variant,
                        target=inject.target,
                    )
                    await flagd.write(desired)
                    await wait_for_document(flagd, desired)
                    ready = await wait_for_flag_variant(
                        flagd,
                        inject.flag,
                        inject.variant,
                        context=inject.target,
                    )
                    if settings.chaos_signal_warmup_seconds:
                        await asyncio.sleep(settings.chaos_signal_warmup_seconds)
                    print(
                        f"[chaos] {item.id}: {inject.flag}={inject.variant} ready "
                        f"after {ready['elapsed_s']:.1f}s; running case",
                        flush=True,
                    )
                    return await base_task(item=item)
                finally:
                    await _complete_cleanup(
                        _restore_document(
                            flagd,
                            original,
                            flag=inject.flag,
                            variant=original_variant,
                            context=inject.target,
                        )
                    )
                    print(f"[chaos] {item.id}: exact pre-case state restored", flush=True)

        def execute_experiment() -> Any:
            return langfuse.run_experiment(
                name="ops_pilot chaos eval",
                run_name=run_name,
                description="serial flagd fault leases with exact recovery",
                data=items,
                task=chaos_task,
                evaluators=build_item_evaluators(settings, include_judge=True),
                run_evaluators=[
                    pass_rate,
                    hitl_safety_rate,
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
                    "case_order": [case.id for case in selected_cases],
                },
            )

        result = await asyncio.to_thread(execute_experiment)
    except BaseException as exc:
        run_error = exc
    finally:
        if runtime is not None:
            try:
                await _close_runtime(runtime)
            except BaseException as exc:
                cleanup_error = exc
        close_langfuse_client(langfuse)

    if cleanup_error is not None:
        print(f"error: chaos cleanup failed: {cleanup_error}")
        return 1
    if run_error is not None:
        if isinstance(run_error, (KeyboardInterrupt, asyncio.CancelledError)):
            raise run_error
        print(f"error: chaos run failed before completion: {run_error}")
        return 1
    if result is None:
        print("error: chaos run produced no experiment result.")
        return 1
    print(result.format())
    return 0 if _run_evaluation_value(result, "pass_rate") >= 1.0 else 1


async def _restore_document(
    flagd: FlagdAPI,
    document: Mapping[str, Any],
    *,
    flag: str,
    variant: str,
    context: Mapping[str, Any] | None,
) -> None:
    await flagd.write(document)
    await wait_for_document(flagd, document)
    await wait_for_flag_variant(flagd, flag, variant, context=context)


async def _complete_cleanup(coro: Any) -> Any:
    """Let restoration finish if the caller is cancelled mid-cleanup."""

    task = asyncio.create_task(coro)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def _targeting_rule(target: Mapping[str, Any], variant: str) -> dict[str, Any]:
    conditions = [{"==": [{"var": key}, value]} for key, value in target.items()]
    condition: dict[str, Any] = conditions[0] if len(conditions) == 1 else {"and": conditions}
    return {"if": [condition, variant, OFF_VARIANT]}


def _parse_document(value: Any, *, source: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(value.get("flags"), Mapping):
        raise ChaosError(f"{source} did not return a flag document: {value!r}")
    return copy.deepcopy(dict(value))


def _same_flag_state(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return left.get("flags") == right.get("flags")


def _variants(document: Mapping[str, Any]) -> dict[str, str]:
    flags = document.get("flags", {})
    return {str(name): str(spec.get("defaultVariant", "")) for name, spec in flags.items() if isinstance(spec, Mapping)}


def _reserve_local_port() -> int:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


def _kubeconfig_from_settings(settings: Settings) -> str:
    for server in settings.mcp.servers:
        if server.name != "kubernetes":
            continue
        if server.env.get("KUBECONFIG"):
            return server.env["KUBECONFIG"]
        args = list(server.args)
        if "--kubeconfig" in args:
            index = args.index("--kubeconfig")
            if index + 1 < len(args):
                return args[index + 1]
        raise ChaosError("kubernetes MCP needs KUBECONFIG or --kubeconfig for chaos control.")
    raise ChaosError("chaos requires a configured kubernetes MCP server.")
