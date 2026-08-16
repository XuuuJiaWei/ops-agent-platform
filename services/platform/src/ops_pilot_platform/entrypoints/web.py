"""The web application's explicit runtime and protocol composition."""

from __future__ import annotations

from dataclasses import dataclass

from copilotkit import CopilotKitMiddleware
from ops_pilot.runtime.spec import RuntimeSpec

from ops_pilot_platform.entrypoints.environment import RuntimeEnvironment
from ops_pilot_platform.entrypoints.profiles import runtime_spec_from_environment


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
    runtime = runtime_spec_from_environment(
        environment,
        id="web",
        entrypoint="web",
        default_assistant_id="agent",
        middleware=(CopilotKitMiddleware(),),
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
