"""LangGraph Platform runtime composition."""

from __future__ import annotations

from ops_pilot.entrypoints.environment import RuntimeEnvironment
from ops_pilot.entrypoints.profiles import (
    model_from_environment,
    observability_from_environment,
    observer_mcp_from_environment,
    project_skills,
    reliability_from_environment,
    sandbox_from_environment,
)
from ops_pilot.runtime.spec import PersistenceSpec, RuntimeSpec


def build_langgraph_runtime_spec(environment: RuntimeEnvironment | None = None) -> RuntimeSpec:
    environment = environment or RuntimeEnvironment.for_entrypoint("langgraph")
    assistant_id = environment.assistant_id or "ops-pilot-langgraph"
    return RuntimeSpec(
        id="langgraph",
        assistant_id=assistant_id,
        entrypoint="langgraph",
        model=model_from_environment(environment),
        mcp=observer_mcp_from_environment(environment),
        skills=project_skills(),
        reliability=reliability_from_environment(environment),
        persistence=PersistenceSpec(),
        sandbox=sandbox_from_environment(environment),
        observability=observability_from_environment(environment),
        attach_checkpointer=False,
    )
