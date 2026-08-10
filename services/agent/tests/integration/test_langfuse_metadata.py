from types import SimpleNamespace

from ops_pilot.config.settings import load_settings
from ops_pilot.observability.langfuse import create_callback_handler
from ops_pilot.observability.metadata import build_model_metadata, build_trace_metadata


def test_langfuse_is_noop_when_keys_are_missing():
    settings = load_settings(env={}, config={"langfuse": {"base_url": "https://cloud.langfuse.com"}})

    tracing = create_callback_handler(settings)

    assert tracing.enabled is False
    assert tracing.callbacks == ()
    assert "LANGFUSE_PUBLIC_KEY" in (tracing.warning or "")


def test_trace_metadata_contains_protocol_ids():
    settings = load_settings(env={}, config={"app_env": "test", "assistant_id": "agent-test"})

    metadata = build_trace_metadata(
        settings,
        protocol="a2a",
        thread_id="thread-1",
        run_id="run-1",
        a2a_task_id="task-1",
    )

    assert metadata["environment"] == "test"
    assert metadata["assistant_id"] == "agent-test"
    assert metadata["protocol"] == "a2a"
    assert metadata["thread_id"] == "thread-1"
    assert metadata["a2a_task_id"] == "task-1"
    assert metadata["langfuse_session_id"] == "thread-1"
    assert metadata["langfuse_trace_name"] == "handle-a2a-task"
    assert metadata["langfuse_tags"] == ["ops_pilot", "a2a", "test"]


def test_trace_metadata_maps_user_id_to_langfuse_user_id():
    settings = load_settings(env={}, config={"app_env": "test", "assistant_id": "agent-test"})

    metadata = build_trace_metadata(
        settings,
        protocol="copilotkit-agui",
        thread_id="thread-1",
        extra={"user_id": "user-1"},
    )

    assert metadata["langfuse_session_id"] == "thread-1"
    assert metadata["langfuse_user_id"] == "user-1"
    assert metadata["langfuse_trace_name"] == "handle-copilotkit-run"


def test_model_metadata_uses_runtime_profile_capacity():
    settings = load_settings(env={}, config={})
    model = SimpleNamespace(
        model_id="anthropic.claude-sonnet-4-6",
        profile={"max_input_tokens": 1_000_000, "max_output_tokens": 64_000, "reasoning_output": True},
    )

    metadata = build_model_metadata(settings, model)

    assert metadata["ls_model_name"] == "anthropic.claude-sonnet-4-6"
    assert metadata["model_context_window_tokens"] == 1_000_000
    assert metadata["model_reasoning_mode"] == "adaptive"
    assert metadata["model_prompt_cache_strategy"] == "deepagents_provider_middleware"
