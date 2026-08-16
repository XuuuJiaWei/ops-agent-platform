from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from ops_pilot.entrypoints.benchmark import build_benchmark_runtime_spec
from ops_pilot.entrypoints.environment import RuntimeEnvironment
from ops_pilot.entrypoints.eval import build_eval_runtime_spec
from ops_pilot.entrypoints.web import build_web_application_spec


def test_entries_select_independent_models_mcp_catalogs_and_extensions(monkeypatch) -> None:
    monkeypatch.delenv("KUBECONFIG", raising=False)
    web = build_web_application_spec(
        RuntimeEnvironment.model_validate(
            {
                "deepagent": {
                    "model": {"provider": "openai", "name": "web-model"},
                    "tools": {"mcp": {"kubernetes": {"kubeconfig": "C:/web/kubeconfig"}}},
                },
            }
        )
    ).runtime
    benchmark = build_benchmark_runtime_spec(
        RuntimeEnvironment.model_validate(
            {
                "deepagent": {
                    "model": {"provider": "deepseek", "name": "benchmark-model"},
                    "tools": {"mcp": {"prometheus": {"url": "https://benchmark.example/mcp"}}},
                },
            }
        )
    )
    evaluation = build_eval_runtime_spec(
        RuntimeEnvironment.model_validate({"deepagent": {"model": {"provider": "anthropic", "name": "eval-model"}}})
    )

    assert (web.model.provider, web.model.name) == ("openai", "web-model")
    assert [server.name for server in web.mcp.servers] == ["kubernetes"]
    assert {factory.__name__ for factory in web.extensions} == {
        "create_copilotkit_runtime_extension",
        "create_spaces_runtime_extension",
    }

    assert (benchmark.model.provider, benchmark.model.name) == ("deepseek", "benchmark-model")
    assert [server.name for server in benchmark.mcp.servers] == ["prometheus"]
    assert benchmark.extensions == ()
    assert benchmark.interrupt_on == {}
    assert benchmark.persistence.backend == "memory"

    assert (evaluation.model.provider, evaluation.model.name) == ("anthropic", "eval-model")
    assert evaluation.extensions == ()
    assert evaluation.persistence.backend == "memory"


def test_entrypoint_yaml_does_not_allow_environment_capability_selection(monkeypatch) -> None:
    monkeypatch.setenv("OPS_PILOT_WEB_MODEL_NAME", "untrusted-web-override")
    monkeypatch.setenv("OPS_PILOT_BENCHMARK_MODEL_NAME", "untrusted-benchmark-override")
    monkeypatch.setenv("OPS_PILOT_SECRET_DEBUG", "true")
    monkeypatch.setenv("OPEN_SANDBOX_API_KEY", "test-key")

    assert build_web_application_spec().runtime.model.name == "deepseek-v4-pro"
    assert build_benchmark_runtime_spec().model.name == "deepseek-v4-pro"
    assert build_eval_runtime_spec().model.name == "deepseek-v4-pro"
    assert build_web_application_spec().runtime.debug is False


def test_entrypoint_yaml_reads_secrets_from_environment_only(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "test-key")

    assert RuntimeEnvironment.for_entrypoint("web").model_api_key == "test-key"


def test_deepagent_injection_points_are_mapped_from_one_normalized_composition() -> None:
    environment = RuntimeEnvironment.model_validate(
        {
            "deepagent": {
                "name": "configured-agent",
                "system_prompt": "Follow the runbook.",
                "memory": ["/memory/AGENTS.md"],
                "permissions": [
                    {
                        "operations": ["read"],
                        "paths": ["/workspace/**"],
                        "mode": "allow",
                    }
                ],
                "middleware": {
                    "todo-list": True,
                    "filesystem": {"tools": ["read_file", "ls", "glob"]},
                },
                "interrupt_on": {"delete_file": True},
                "checkpointer": {"backend": "none"},
                "debug": True,
            },
        }
    )

    runtime = build_eval_runtime_spec(environment)

    assert runtime.name == "configured-agent"
    assert runtime.system_prompt == "Follow the runbook."
    assert runtime.memory == ("/memory/AGENTS.md",)
    assert runtime.permissions[0].as_deepagents_permission() == {
        "operations": ["read"],
        "paths": ["/workspace/**"],
        "mode": "allow",
    }
    assert runtime.todo_list_enabled is True
    assert runtime.filesystem_tools == ("read_file", "ls", "glob")
    assert runtime.interrupt_on == {"delete_file": True}
    assert runtime.persistence.backend == "none"
    assert runtime.debug is True


def test_entrypoint_yaml_rejects_nested_secrets(tmp_path) -> None:
    config = tmp_path / "entry.yaml"
    config.write_text(
        "deepagent:\n  model:\n    provider: deepseek\n    api-key: must-not-be-here\n",
        encoding="utf-8",
    )

    class SecretYamlEnvironment(RuntimeEnvironment):
        model_config = SettingsConfigDict(yaml_file=config)

    with pytest.raises(ValueError, match="deepagent.model.api-key"):
        SecretYamlEnvironment()


def test_environment_rejects_invalid_typed_deployment_value() -> None:
    with pytest.raises(ValidationError):
        RuntimeEnvironment.model_validate({"server": {"port": cast(Any, "not-a-port")}})
