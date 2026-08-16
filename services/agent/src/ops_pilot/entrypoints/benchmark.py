"""AIOpsLab's deliberately isolated runtime composition."""

from __future__ import annotations

from ops_pilot.entrypoints.environment import RuntimeEnvironment
from ops_pilot.entrypoints.profiles import (
    checkpointer_from_environment,
    deepagent_fields_from_environment,
    model_from_environment,
    observability_from_environment,
    observer_mcp_from_environment,
    reliability_from_environment,
    sandbox_from_environment,
)
from ops_pilot.runtime.spec import RuntimeSpec


def build_benchmark_runtime_spec(environment: RuntimeEnvironment | None = None) -> RuntimeSpec:
    environment = environment or RuntimeEnvironment.for_entrypoint("benchmark")
    assistant_id = environment.deepagent.name or "ops-pilot-benchmark"
    return RuntimeSpec(
        id="benchmark-aiopslab",
        assistant_id=assistant_id,
        entrypoint="benchmark:aiopslab",
        model=model_from_environment(environment),
        mcp=observer_mcp_from_environment(environment),
        **deepagent_fields_from_environment(environment),
        reliability=reliability_from_environment(environment),
        persistence=checkpointer_from_environment(environment),
        sandbox=sandbox_from_environment(environment),
        observability=observability_from_environment(environment),
        metadata={"benchmark": "aiopslab"},
    )
