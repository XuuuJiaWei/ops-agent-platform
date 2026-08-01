"""Langfuse callback setup with local no-op behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ops_pilot.config.settings import Settings


@dataclass(frozen=True)
class TracingSetup:
    enabled: bool
    callbacks: tuple[Any, ...] = field(default_factory=tuple)
    warning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "callback_count": len(self.callbacks),
            "warning": self.warning,
        }


def create_callback_handler(settings: Settings) -> TracingSetup:
    """Create a Langfuse callback handler or return disabled local status."""

    missing = _missing_langfuse_keys(settings)
    if missing:
        return TracingSetup(
            enabled=False,
            warning=(
                "Langfuse tracing disabled; missing required environment values: "
                + ", ".join(missing)
            ),
        )

    try:
        from langfuse.langchain import CallbackHandler
    except ImportError as exc:
        return TracingSetup(
            enabled=False,
            warning=f"Langfuse tracing disabled; langfuse package import failed: {exc}",
        )

    return TracingSetup(enabled=True, callbacks=(CallbackHandler(),))


def flush_tracing(tracing: TracingSetup) -> None:
    """Flush tracing callbacks when the underlying handler exposes a flush API."""

    for callback in tracing.callbacks:
        flush = getattr(callback, "flush", None)
        if callable(flush):
            flush()


def _missing_langfuse_keys(settings: Settings) -> tuple[str, ...]:
    missing: list[str] = []
    if not settings.langfuse_public_key:
        missing.append("LANGFUSE_PUBLIC_KEY")
    if not settings.langfuse_secret_key:
        missing.append("LANGFUSE_SECRET_KEY")
    if not settings.langfuse_base_url:
        missing.append("LANGFUSE_BASE_URL")
    return tuple(missing)

