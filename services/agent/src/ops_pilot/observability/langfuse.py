"""Langfuse's official singleton client and LangChain callback integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ops_pilot.runtime.spec import ObservabilitySpec


@dataclass(frozen=True)
class TracingSetup:
    enabled: bool
    callbacks: tuple[Any, ...] = field(default_factory=tuple)
    client: Any | None = None
    warning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "callback_count": len(self.callbacks),
            "warning": self.warning,
        }


def get_langfuse_client(spec: ObservabilitySpec) -> Any:
    """Configure once and return the SDK client registered for this project."""

    from langfuse import Langfuse, get_client

    Langfuse(
        public_key=spec.public_key,
        secret_key=spec.secret_key,
        base_url=spec.base_url,
        timeout=spec.timeout_seconds,
        environment=spec.environment,
    )
    return get_client(public_key=spec.public_key)


def create_callback_handler(spec: ObservabilitySpec) -> TracingSetup:
    """Create the official LangChain handler or a local no-op status."""

    if not spec.enabled:
        return TracingSetup(enabled=False, warning="Langfuse tracing disabled by entrypoint configuration")

    missing = _missing_langfuse_keys(spec)
    if missing:
        return TracingSetup(
            enabled=False,
            warning=("Langfuse tracing disabled; missing required environment values: " + ", ".join(missing)),
        )

    try:
        from langfuse.langchain import CallbackHandler

        client = get_langfuse_client(spec)
    except ImportError as exc:
        return TracingSetup(
            enabled=False,
            warning=f"Langfuse tracing disabled; langfuse package import failed: {exc}",
        )

    return TracingSetup(
        enabled=True,
        callbacks=(CallbackHandler(),),
        client=client,
    )


def describe_tracing(spec: ObservabilitySpec) -> TracingSetup:
    """Describe tracing configuration without creating an SDK client."""

    if not spec.enabled:
        return TracingSetup(enabled=False, warning="Langfuse tracing disabled by entrypoint configuration")
    missing = _missing_langfuse_keys(spec)
    if missing:
        return TracingSetup(
            enabled=False,
            warning=("Langfuse tracing disabled; missing required environment values: " + ", ".join(missing)),
        )
    return TracingSetup(enabled=True)


def flush_tracing(tracing: TracingSetup) -> None:
    """Flush buffered events without owning or replacing the SDK's OTel provider."""

    if tracing.client is not None:
        tracing.client.flush()


def _missing_langfuse_keys(spec: ObservabilitySpec) -> tuple[str, ...]:
    missing: list[str] = []
    if not spec.public_key:
        missing.append("LANGFUSE_PUBLIC_KEY")
    if not spec.secret_key:
        missing.append("LANGFUSE_SECRET_KEY")
    if not spec.base_url:
        missing.append("LANGFUSE_BASE_URL")
    return tuple(missing)
