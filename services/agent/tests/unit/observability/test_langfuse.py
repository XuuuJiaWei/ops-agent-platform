from ops_pilot.observability.langfuse import TracingSetup, flush_tracing


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
