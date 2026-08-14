"""Langfuse's official singleton client and LangChain callback integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ops_pilot.config.settings import Settings


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


def get_langfuse_client(settings: Settings) -> Any:
    """Configure once and return the SDK client registered for this project."""

    from langfuse import Langfuse, get_client

    Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
        timeout=settings.langfuse_timeout_seconds,
        environment=settings.app_env,
    )
    return get_client(public_key=settings.langfuse_public_key)


def create_callback_handler(settings: Settings) -> TracingSetup:
    """Create the official LangChain handler or a local no-op status."""

    missing = _missing_langfuse_keys(settings)
    if missing:
        return TracingSetup(
            enabled=False,
            warning=("Langfuse tracing disabled; missing required environment values: " + ", ".join(missing)),
        )

    try:
        from langfuse.langchain import CallbackHandler

        client = get_langfuse_client(settings)
    except ImportError as exc:
        return TracingSetup(
            enabled=False,
            warning=f"Langfuse tracing disabled; langfuse package import failed: {exc}",
        )

    return TracingSetup(
        enabled=True,
        callbacks=(CallbackHandler(public_key=settings.langfuse_public_key),),
        client=client,
    )


def flush_tracing(tracing: TracingSetup) -> None:
    """Flush buffered events without owning or replacing the SDK's OTel provider."""

    if tracing.client is not None:
        tracing.client.flush()


def _missing_langfuse_keys(settings: Settings) -> tuple[str, ...]:
    missing: list[str] = []
    if not settings.langfuse_public_key:
        missing.append("LANGFUSE_PUBLIC_KEY")
    if not settings.langfuse_secret_key:
        missing.append("LANGFUSE_SECRET_KEY")
    if not settings.langfuse_base_url:
        missing.append("LANGFUSE_BASE_URL")
    return tuple(missing)
