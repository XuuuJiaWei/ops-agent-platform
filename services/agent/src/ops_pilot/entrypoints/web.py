"""The web application's explicit runtime and protocol composition."""

from __future__ import annotations

from dataclasses import dataclass

from ops_pilot.agui.runtime import create_copilotkit_runtime_extension
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
from ops_pilot.spaces.runtime import create_spaces_runtime_extension


@dataclass(frozen=True)
class WebApplicationSpec:
    runtime: RuntimeSpec
    host: str = "127.0.0.1"
    port: int = 8123
    chat_base_path: str = "/chat"
    a2a_base_path: str = "/a2a"
    enable_spaces: bool = True
    enable_a2a: bool = True


def build_web_application_spec(environment: RuntimeEnvironment | None = None) -> WebApplicationSpec:
    environment = environment or RuntimeEnvironment.for_entrypoint("web")
    runtime = RuntimeSpec(
        id="web",
        assistant_id=environment.name or "agent",
        entrypoint="web",
        model=model_from_environment(environment),
        mcp=observer_mcp_from_environment(environment),
        **deepagent_fields_from_environment(environment),
        reliability=reliability_from_environment(environment),
        persistence=checkpointer_from_environment(environment),
        sandbox=sandbox_from_environment(environment),
        observability=observability_from_environment(environment),
        extensions=(create_spaces_runtime_extension, create_copilotkit_runtime_extension),
        metadata={"surface": "web"},
    )
    return WebApplicationSpec(
        runtime=runtime,
        host=environment.server.host,
        port=environment.server.port,
        chat_base_path=environment.server.chat.base_path,
        a2a_base_path=environment.server.a2a.base_path,
        enable_spaces=environment.web.spaces.enabled,
        enable_a2a=environment.server.a2a.enabled,
    )
