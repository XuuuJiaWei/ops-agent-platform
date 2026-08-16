"""Offline evaluation runtime composition."""

from __future__ import annotations

from ops_pilot.runtime.spec import RuntimeSpec

from ops_pilot_platform.entrypoints.environment import RuntimeEnvironment
from ops_pilot_platform.entrypoints.profiles import runtime_spec_from_environment


def build_eval_runtime_spec(environment: RuntimeEnvironment | None = None) -> RuntimeSpec:
    environment = environment or RuntimeEnvironment.for_entrypoint("eval")
    return runtime_spec_from_environment(
        environment,
        id="eval",
        entrypoint="eval",
        default_assistant_id="ops-pilot-eval",
        metadata={"evaluation": True},
    )
