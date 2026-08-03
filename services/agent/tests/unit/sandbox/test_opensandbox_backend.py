from __future__ import annotations

from ops_pilot.config.settings import load_settings
from ops_pilot.sandbox import opensandbox_backend
from ops_pilot.sandbox.opensandbox_backend import create_sandbox_runtime


class FakeConnectionConfig:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class FakeSandbox:
    created_image = None
    created_kwargs = None

    def __init__(self) -> None:
        self.id = "sandbox-123"
        self.destroyed = False
        self.closed = False

    @classmethod
    def create(cls, image: str, **kwargs: object) -> FakeSandbox:
        cls.created_image = image
        cls.created_kwargs = kwargs
        return cls()

    def destroy(self) -> None:
        self.destroyed = True

    def close(self) -> None:
        self.closed = True


class FakeBackend:
    def __init__(self, *, sandbox: FakeSandbox) -> None:
        self.sandbox = sandbox


def test_create_sandbox_runtime_returns_none_when_disabled() -> None:
    settings = load_settings({})

    assert create_sandbox_runtime(settings) is None


def test_create_sandbox_runtime_builds_opensandbox_backend(monkeypatch) -> None:
    monkeypatch.setattr(
        opensandbox_backend,
        "_load_opensandbox_symbols",
        lambda: opensandbox_backend._OpenSandboxSymbols(
            backend_cls=FakeBackend,
            sandbox_cls=FakeSandbox,
            connection_config_cls=FakeConnectionConfig,
        ),
    )
    settings = load_settings(
        {
            "OPEN_SANDBOX_DOMAIN": "opensandbox.example.test",
            "OPEN_SANDBOX_API_KEY": "secret",
        }
    )

    runtime = create_sandbox_runtime(settings)

    assert runtime is not None
    assert runtime.sandbox_id == "sandbox-123"
    assert runtime.backend.sandbox is runtime.sandbox
    assert FakeSandbox.created_image == "python:3.11"
    assert FakeSandbox.created_kwargs is not None
    assert FakeSandbox.created_kwargs["entrypoint"] == ["tail", "-f", "/dev/null"]
    assert FakeSandbox.created_kwargs["resource"] == {"cpu": "250m", "memory": "256Mi"}
    assert FakeSandbox.created_kwargs["resource_requests"] == {
        "cpu": "100m",
        "memory": "128Mi",
    }
    assert FakeSandbox.created_kwargs["timeout"].total_seconds() == 600
    assert FakeSandbox.created_kwargs["ready_timeout"].total_seconds() == 240
    connection = FakeSandbox.created_kwargs["connection_config"]
    assert connection.kwargs == {
        "domain": "opensandbox.example.test",
        "protocol": "https",
        "api_key": "secret",
        "use_server_proxy": True,
        "disable_metrics": True,
    }

    runtime.close()

    assert runtime.sandbox.destroyed is True
    assert runtime.sandbox.closed is True


def test_sandbox_runtime_status_does_not_include_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        opensandbox_backend,
        "_load_opensandbox_symbols",
        lambda: opensandbox_backend._OpenSandboxSymbols(
            backend_cls=FakeBackend,
            sandbox_cls=FakeSandbox,
            connection_config_cls=FakeConnectionConfig,
        ),
    )
    settings = load_settings(
        {
            "OPEN_SANDBOX_DOMAIN": "opensandbox.example.test",
            "OPEN_SANDBOX_API_KEY": "secret",
        }
    )

    runtime = create_sandbox_runtime(settings)

    assert runtime is not None
    assert "secret" not in str(runtime.as_dict())
