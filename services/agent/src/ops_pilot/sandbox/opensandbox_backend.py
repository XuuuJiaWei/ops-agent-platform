"""OpenSandbox-backed DeepAgents filesystem and command backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from ops_pilot.config.settings import Settings


class _OpenSandboxSymbols(NamedTuple):
    backend_cls: type[Any]
    sandbox_cls: type[Any]
    connection_config_cls: type[Any]


@dataclass
class SandboxRuntime:
    """Runtime-owned sandbox resources passed into DeepAgents."""

    backend: Any
    sandbox: Any
    mode: str = "opensandbox"
    image: str = "python:3.11"
    domain: str | None = None
    protocol: str = "https"
    use_server_proxy: bool = True
    timeout_seconds: int | None = None
    lease_started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def sandbox_id(self) -> str | None:
        sandbox_id = getattr(self.sandbox, "id", None)
        return str(sandbox_id) if sandbox_id is not None else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "mode": self.mode,
            "image": self.image,
            "domain": self.domain,
            "protocol": self.protocol,
            "use_server_proxy": self.use_server_proxy,
            "sandbox_id": self.sandbox_id,
            "timeout_seconds": self.timeout_seconds,
            "expires_at": self.expires_at.isoformat() if self.expires_at is not None else None,
        }

    @property
    def expires_at(self) -> datetime | None:
        if self.timeout_seconds is None:
            return None
        return self.lease_started_at + timedelta(seconds=self.timeout_seconds)

    def is_expired(self, now: datetime | None = None) -> bool:
        expires_at = self.expires_at
        if expires_at is None:
            return False
        return (now or datetime.now(UTC)) >= expires_at

    def should_renew(self, now: datetime | None = None) -> bool:
        if self.timeout_seconds is None:
            return False
        elapsed = ((now or datetime.now(UTC)) - self.lease_started_at).total_seconds()
        return elapsed >= min(self.timeout_seconds / 2, 60)

    def renew(self) -> bool:
        """Renew the remote sandbox lease when a TTL is configured.

        Returns false when the remote sandbox is already gone and the caller
        should rebuild the runtime with a fresh sandbox.
        """

        if self.timeout_seconds is None:
            return True
        renew = getattr(self.sandbox, "renew", None)
        if renew is None:
            return not self.is_expired()
        try:
            renew(timedelta(seconds=self.timeout_seconds))
        except Exception as exc:  # noqa: BLE001 - SDK raises different subclasses across versions.
            if _is_sandbox_not_found_error(exc):
                return False
            raise
        self.lease_started_at = datetime.now(UTC)
        return True

    def close(self) -> None:
        """Release remote sandbox resources owned by this runtime."""

        if self._closed:
            return
        self._closed = True
        terminate = getattr(self.sandbox, "destroy", None) or getattr(self.sandbox, "kill", None)
        try:
            if terminate is not None:
                try:
                    terminate()
                except Exception as exc:  # noqa: BLE001 - SDK raises different subclasses across versions.
                    if not _is_sandbox_not_found_error(exc):
                        raise
        finally:
            close = getattr(self.sandbox, "close", None)
            if close is not None:
                close()


def create_sandbox_runtime(settings: Settings) -> SandboxRuntime | None:
    """Create the configured DeepAgents sandbox backend, if enabled."""

    if not settings.open_sandbox_enabled:
        return None
    if not settings.open_sandbox_domain:
        raise RuntimeError("OPEN_SANDBOX_DOMAIN is required when OPEN_SANDBOX_ENABLED is true.")
    if not settings.open_sandbox_api_key:
        raise RuntimeError("OPEN_SANDBOX_API_KEY is required when OPEN_SANDBOX_ENABLED is true.")

    symbols = _load_opensandbox_symbols()
    connection = symbols.connection_config_cls(
        api_key=settings.open_sandbox_api_key,
        domain=settings.open_sandbox_domain,
        protocol=settings.open_sandbox_protocol,
        use_server_proxy=settings.open_sandbox_use_server_proxy,
        disable_metrics=settings.open_sandbox_disable_metrics,
    )
    sandbox_timeout = (
        timedelta(seconds=settings.open_sandbox_timeout_seconds)
        if settings.open_sandbox_timeout_seconds is not None
        else None
    )
    sandbox = symbols.sandbox_cls.create(
        settings.open_sandbox_image,
        timeout=sandbox_timeout,
        ready_timeout=timedelta(seconds=settings.open_sandbox_ready_timeout_seconds),
        resource={
            "cpu": settings.open_sandbox_cpu_limit,
            "memory": settings.open_sandbox_memory_limit,
        },
        resource_requests={
            "cpu": settings.open_sandbox_cpu_request,
            "memory": settings.open_sandbox_memory_request,
        },
        env={},
        entrypoint=["tail", "-f", "/dev/null"],
        connection_config=connection,
    )
    backend = symbols.backend_cls(sandbox=sandbox)
    return SandboxRuntime(
        backend=backend,
        sandbox=sandbox,
        image=settings.open_sandbox_image,
        domain=settings.open_sandbox_domain,
        protocol=settings.open_sandbox_protocol,
        use_server_proxy=settings.open_sandbox_use_server_proxy,
        timeout_seconds=settings.open_sandbox_timeout_seconds,
    )


def _load_opensandbox_symbols() -> _OpenSandboxSymbols:
    try:
        from deepagents_opensandbox import OpensandboxBackend
        from opensandbox import SandboxSync
        from opensandbox.config import ConnectionConfigSync
    except ImportError as exc:
        raise RuntimeError("OpenSandbox support is not installed. Run 'uv sync' in services/agent.") from exc
    return _OpenSandboxSymbols(
        backend_cls=OpensandboxBackend,
        sandbox_cls=SandboxSync,
        connection_config_cls=ConnectionConfigSync,
    )


def _is_sandbox_not_found_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "sandbox" in text and "not found" in text
