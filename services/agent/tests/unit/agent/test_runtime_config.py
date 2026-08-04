from __future__ import annotations

from dataclasses import dataclass

from ops_pilot.agent.runtime import AgentRuntime
from ops_pilot.config.settings import load_settings


@dataclass(frozen=True)
class DummyGraph:
    config: dict[str, object] | None = None


def test_runnable_config_forwards_deepagents_recursion_limit_as_top_level_key() -> None:
    runtime = AgentRuntime(
        graph=DummyGraph(config={"recursion_limit": 1234}),
        settings=load_settings({"APP_ENV": "test"}),
    )

    config = runtime.runnable_config(
        protocol="copilotkit-agui",
        thread_id="thread-1",
        configurable={"tenant": "local"},
    )

    assert config["recursion_limit"] == 1234
    assert config["configurable"] == {"tenant": "local", "thread_id": "thread-1"}


def test_runnable_config_does_not_invent_recursion_limit_when_graph_has_no_bound_config() -> None:
    runtime = AgentRuntime(graph=object(), settings=load_settings({"APP_ENV": "test"}))

    config = runtime.runnable_config(protocol="smoke")

    assert "recursion_limit" not in config
