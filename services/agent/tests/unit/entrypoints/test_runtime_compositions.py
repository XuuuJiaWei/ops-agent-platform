from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from ops_pilot.entrypoints.benchmark import build_benchmark_runtime_spec
from ops_pilot.entrypoints.environment import RuntimeEnvironment
from ops_pilot.entrypoints.eval import build_eval_runtime_spec
from ops_pilot.entrypoints.web import build_web_application_spec


def test_entries_select_independent_models_mcp_catalogs_and_extensions(monkeypatch) -> None:
    monkeypatch.delenv("KUBECONFIG", raising=False)
    web = build_web_application_spec(
        RuntimeEnvironment(model_provider="openai", model_name="web-model", kubeconfig="C:/web/kubeconfig")
    ).runtime
    benchmark = build_benchmark_runtime_spec(
        RuntimeEnvironment(
            model_provider="deepseek",
            model_name="benchmark-model",
            prometheus_mcp_url="https://benchmark.example/mcp",
        )
    )
    evaluation = build_eval_runtime_spec(RuntimeEnvironment(model_provider="anthropic", model_name="eval-model"))

    assert (web.model.provider, web.model.name) == ("openai", "web-model")
    assert [server.name for server in web.mcp.servers] == ["kubernetes"]
    assert {factory.__name__ for factory in web.extensions} == {
        "create_copilotkit_runtime_extension",
        "create_spaces_runtime_extension",
    }

    assert (benchmark.model.provider, benchmark.model.name) == ("deepseek", "benchmark-model")
    assert [server.name for server in benchmark.mcp.servers] == ["prometheus"]
    assert benchmark.extensions == ()
    assert benchmark.bypass_hitl is True
    assert benchmark.attach_checkpointer is False

    assert (evaluation.model.provider, evaluation.model.name) == ("anthropic", "eval-model")
    assert evaluation.extensions == ()
    assert evaluation.persistence.backend == "memory"


def test_entrypoint_yaml_does_not_allow_environment_capability_selection(monkeypatch) -> None:
    monkeypatch.setenv("OPS_PILOT_WEB_MODEL_NAME", "untrusted-web-override")
    monkeypatch.setenv("OPS_PILOT_BENCHMARK_MODEL_NAME", "untrusted-benchmark-override")

    assert build_web_application_spec().runtime.model.name == "deepseek-v4-pro"
    assert build_benchmark_runtime_spec().model.name == "deepseek-v4-pro"
    assert build_eval_runtime_spec().model.name == "deepseek-v4-pro"


def test_entrypoint_yaml_reads_secrets_from_environment_only(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "test-key")

    assert RuntimeEnvironment.for_entrypoint("web").model_api_key == "test-key"


def test_environment_rejects_invalid_typed_deployment_value() -> None:
    with pytest.raises(ValidationError):
        RuntimeEnvironment(port=cast(Any, "not-a-port"))
