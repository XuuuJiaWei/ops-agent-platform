from ops_pilot.config.settings import load_settings
from ops_pilot.observability.langfuse import create_callback_handler
from ops_pilot.observability.metadata import build_trace_metadata


def test_langfuse_is_noop_when_keys_are_missing():
    settings = load_settings({"LANGFUSE_BASE_URL": "https://cloud.langfuse.com"})

    tracing = create_callback_handler(settings)

    assert tracing.enabled is False
    assert tracing.callbacks == ()
    assert "LANGFUSE_PUBLIC_KEY" in (tracing.warning or "")


def test_trace_metadata_contains_protocol_ids():
    settings = load_settings({"APP_ENV": "test", "ASSISTANT_ID": "agent-test"})

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

