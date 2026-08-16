"""AIOpsLab's deliberately isolated runtime composition."""

from __future__ import annotations

from ops_pilot.entrypoints.environment import RuntimeEnvironment
from ops_pilot.entrypoints.profiles import (
    model_from_environment,
    observability_from_environment,
    observer_mcp_from_environment,
    persistence_from_environment,
    project_skills,
    reliability_from_environment,
    sandbox_from_environment,
)
from ops_pilot.runtime.spec import RuntimeSpec


def build_benchmark_runtime_spec(environment: RuntimeEnvironment | None = None) -> RuntimeSpec:
    environment = environment or RuntimeEnvironment.for_entrypoint("benchmark")
    assistant_id = environment.assistant_id or "ops-pilot-benchmark"
    return RuntimeSpec(
        id="benchmark-aiopslab",
        assistant_id=assistant_id,
        entrypoint="benchmark:aiopslab",
        model=model_from_environment(environment),
        mcp=observer_mcp_from_environment(environment),
        system_prompt=environment.system_prompt,
        skills=project_skills(),
        reliability=reliability_from_environment(environment),
        persistence=persistence_from_environment(environment),
        sandbox=sandbox_from_environment(environment),
        observability=observability_from_environment(environment),
        bypass_hitl=True,
        attach_checkpointer=False,
        metadata={"benchmark": "aiopslab"},
    )
