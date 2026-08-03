"""OpenSandbox-backed DeepAgents filesystem and command backend."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, NamedTuple

from ops_pilot.config.paths import REPO_ROOT
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
        }

    def close(self) -> None:
        """Release remote sandbox resources owned by this runtime."""

        if self._closed:
            return
        self._closed = True
        terminate = getattr(self.sandbox, "destroy", None) or getattr(self.sandbox, "kill", None)
        try:
            if terminate is not None:
                terminate()
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
        domain=settings.open_sandbox_domain,
        protocol=settings.open_sandbox_protocol,
        api_key=settings.open_sandbox_api_key,
        use_server_proxy=settings.open_sandbox_use_server_proxy,
        disable_metrics=settings.open_sandbox_disable_metrics,
    )
    sandbox = symbols.sandbox_cls.create(
        settings.open_sandbox_image,
        timeout=timedelta(seconds=settings.open_sandbox_timeout_seconds),
        ready_timeout=timedelta(seconds=settings.open_sandbox_ready_timeout_seconds),
        resource={
            "cpu": settings.open_sandbox_cpu_limit,
            "memory": settings.open_sandbox_memory_limit,
        },
        resource_requests={
            "cpu": settings.open_sandbox_cpu_request,
            "memory": settings.open_sandbox_memory_request,
        },
        env=_dynatrace_sandbox_env(),
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
    )


def _load_opensandbox_symbols() -> _OpenSandboxSymbols:
    try:
        from deepagents_opensandbox import OpensandboxBackend
        from opensandbox import SandboxSync
        from opensandbox.config import ConnectionConfigSync
    except ImportError as exc:
        raise RuntimeError(
            "OpenSandbox support is not installed. Run 'uv sync' in services/agent."
        ) from exc
    return _OpenSandboxSymbols(
        backend_cls=OpensandboxBackend,
        sandbox_cls=SandboxSync,
        connection_config_cls=ConnectionConfigSync,
    )


def _dynatrace_sandbox_env() -> dict[str, str]:
    values = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("DT_") and key.endswith("_TOKEN") and value
    }
    for entry in _read_dt_config_entries(REPO_ROOT / "config" / "dt-config.yaml"):
        alias = entry.get("alias")
        if not alias:
            continue
        prefix = f"DT_{_env_key(alias)}"
        endpoint = entry.get("apiEndpointUrl") or entry.get("dynatraceUrl")
        if endpoint:
            values[f"{prefix}_URL"] = endpoint
        if entry.get("environmentId"):
            values[f"{prefix}_ENVIRONMENT_ID"] = entry["environmentId"]
    return values


def _read_dt_config_entries(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            if current:
                entries.append(current)
            current = {}
            line = line[1:].strip()
            if not line:
                continue
        if ":" in line and current is not None:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip().strip('"\'')
    if current:
        entries.append(current)
    return entries


def _env_key(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value.upper())
