"""LangGraph Platform runtime composition."""

from __future__ import annotations

from ops_pilot.runtime.spec import RuntimeSpec

from ops_pilot_platform.entrypoints.environment import RuntimeEnvironment
from ops_pilot_platform.entrypoints.profiles import runtime_spec_from_environment


def build_langgraph_runtime_spec(environment: RuntimeEnvironment | None = None) -> RuntimeSpec:
    environment = environment or RuntimeEnvironment.for_entrypoint("langgraph")
    return runtime_spec_from_environment(
        environment,
        id="langgraph",
        entrypoint="langgraph",
        default_assistant_id="ops-pilot-langgraph",
    )
