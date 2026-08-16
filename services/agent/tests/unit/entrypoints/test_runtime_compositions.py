from __future__ import annotations

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


def test_an_entry_reads_only_its_own_prefixed_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPS_PILOT_WEB_MODEL_NAME", "web-only")
    monkeypatch.setenv("OPS_PILOT_BENCHMARK_MODEL_NAME", "benchmark-only")

    assert build_web_application_spec().runtime.model.name == "web-only"
    assert build_benchmark_runtime_spec().model.name == "benchmark-only"
    assert build_eval_runtime_spec().model.name == "anthropic--claude-4.6-sonnet"


def test_environment_rejects_invalid_typed_deployment_value(monkeypatch) -> None:
    monkeypatch.setenv("OPS_PILOT_WEB_PORT", "not-a-port")

    with pytest.raises(ValidationError):
        RuntimeEnvironment.for_entrypoint("web")
