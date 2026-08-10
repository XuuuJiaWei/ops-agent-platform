"""Langfuse callback setup with local no-op behavior."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
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


def create_callback_handler(settings: Settings) -> TracingSetup:
    """Create a Langfuse callback handler or return disabled local status."""

    missing = _missing_langfuse_keys(settings)
    if missing:
        return TracingSetup(
            enabled=False,
            warning=("Langfuse tracing disabled; missing required environment values: " + ", ".join(missing)),
        )

    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
    except ImportError as exc:
        return TracingSetup(
            enabled=False,
            warning=f"Langfuse tracing disabled; langfuse package import failed: {exc}",
        )

    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
        environment=settings.app_env,
    )
    return TracingSetup(
        enabled=True,
        callbacks=(CallbackHandler(public_key=settings.langfuse_public_key),),
        client=client,
    )


def flush_tracing(tracing: TracingSetup) -> None:
    """Flush tracing callbacks when the underlying handler exposes a flush API."""

    targets = (*tracing.callbacks, tracing.client)
    seen: set[int] = set()
    for target in targets:
        if target is None or id(target) in seen:
            continue
        seen.add(id(target))
        flush = getattr(target, "flush", None)
        if callable(flush):
            flush()


@contextmanager
def observation(
    tracing: TracingSetup,
    *,
    name: str,
    as_type: str = "span",
    input: Any | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Create a current Langfuse observation or a transparent no-op context.

    Framework callbacks executed inside this context inherit it through the
    OpenTelemetry context, so LangChain generations and tools are nested under
    the application-level agent/phase that actually owns them.
    """

    if not tracing.enabled or tracing.client is None:
        yield None
        return
    with tracing.client.start_as_current_observation(
        name=name,
        as_type=as_type,
        input=input,
        metadata=dict(metadata or {}),
    ) as current:
        yield current


def finish_observation(
    current: Any | None,
    *,
    output: Any | None = None,
    error: BaseException | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Update an optional observation with its terminal result."""

    if current is None:
        return
    values: dict[str, Any] = {"output": output}
    if metadata:
        values["metadata"] = dict(metadata)
    if error is not None:
        values.update(level="ERROR", status_message=str(error) or type(error).__name__)
    current.update(**values)


def _missing_langfuse_keys(settings: Settings) -> tuple[str, ...]:
    missing: list[str] = []
    if not settings.langfuse_public_key:
        missing.append("LANGFUSE_PUBLIC_KEY")
    if not settings.langfuse_secret_key:
        missing.append("LANGFUSE_SECRET_KEY")
    if not settings.langfuse_base_url:
        missing.append("LANGFUSE_BASE_URL")
    return tuple(missing)
