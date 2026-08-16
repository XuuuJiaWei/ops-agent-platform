"""AIOpsLab's deliberately isolated runtime composition."""

from __future__ import annotations

from typing import Any

from ops_pilot.runtime.spec import RuntimeSpec

from ops_pilot_platform.entrypoints.environment import RuntimeEnvironment
from ops_pilot_platform.entrypoints.profiles import runtime_spec_from_environment


def build_benchmark_runtime_spec(environment: RuntimeEnvironment | None = None) -> RuntimeSpec:
    environment = environment or RuntimeEnvironment.for_entrypoint("benchmark")
    return runtime_spec_from_environment(
        environment,
        id="benchmark-aiopslab",
        entrypoint="benchmark:aiopslab",
        default_assistant_id="ops-pilot-benchmark",
        metadata={"benchmark": "aiopslab"},
    )


def build_rca100_runtime_spec(
    environment: RuntimeEnvironment | None = None,
    *,
    tools: tuple[Any, ...] = (),
    context_schema: type[Any] | None = None,
    response_format: Any | None = None,
) -> RuntimeSpec:
    """Compose the RCA100 host through DeepAgents' official injection points."""

    environment = environment or RuntimeEnvironment.for_entrypoint("rca100")
    return runtime_spec_from_environment(
        environment,
        id="benchmark-rca100",
        entrypoint="benchmark:rca100",
        default_assistant_id="ops-pilot-sre-diagnosis",
        tools=tools,
        context_schema=context_schema,
        response_format=response_format,
        metadata={"benchmark": "rca100"},
    )
