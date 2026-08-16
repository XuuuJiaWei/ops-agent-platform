from ops_pilot.observability.langfuse import TracingSetup, create_callback_handler, flush_tracing
from ops_pilot.runtime.spec import ObservabilitySpec


class _FakeClient:
    def __init__(self) -> None:
        self.flushes = 0

    def flush(self) -> None:
        self.flushes += 1


def test_flush_tracing_delegates_to_the_official_client() -> None:
    client = _FakeClient()

    flush_tracing(TracingSetup(enabled=True, client=client))

    assert client.flushes == 1


def test_flush_tracing_is_noop_without_a_client() -> None:
    flush_tracing(TracingSetup(enabled=False))


def test_callback_handler_does_not_enable_langfuse_without_entrypoint_opt_in() -> None:
    tracing = create_callback_handler(ObservabilitySpec(public_key="public-key", secret_key="secret-key"))

    assert tracing.enabled is False
    assert tracing.warning == "Langfuse tracing disabled by entrypoint configuration"
