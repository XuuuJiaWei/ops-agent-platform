"""Host-neutral declarations for assembling one DeepAgents runtime.

An entrypoint owns a :class:`RuntimeSpec`.  The core runtime only consumes this
already-declared composition; it never discovers a global configuration file.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ops_pilot.mcp.spec import MCPServerCatalog

if TYPE_CHECKING:
    from ops_pilot.agent.extensions import RuntimeExtension

    RuntimeExtensionFactory = Callable[["RuntimeSpec"], Awaitable[RuntimeExtension]]
else:
    RuntimeExtensionFactory = Callable[..., Awaitable[Any]]

ModelProvider = Literal["sap", "openai", "deepseek", "anthropic", "google_genai", "ollama"]
PersistenceBackend = Literal["memory", "postgres", "none"]
SandboxScope = Literal["process", "thread", "run"]
ReasoningMode = Literal["adaptive", "disabled"]
ReasoningEffort = Literal["low", "medium", "high"]
FilesystemOperation = Literal["read", "write"]
FilesystemPermissionMode = Literal["allow", "deny", "interrupt"]


@dataclass(frozen=True)
class ModelSpec:
    provider: ModelProvider
    name: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    top_p: float | None = None
    max_tokens: int | None = 16384
    request_timeout_seconds: int = 120
    reasoning_mode: ReasoningMode = "adaptive"
    reasoning_effort: ReasoningEffort = "medium"


@dataclass(frozen=True)
class ReliabilitySpec:
    enabled: bool = True
    run_deadline_seconds: float | None = 600.0
    model_call_limit: int = 50
    tool_call_limit: int = 200
    tool_retry_max_retries: int = 2
    tool_retry_initial_delay_seconds: float = 0.25
    tool_retry_backoff_factor: float = 2.0
    tool_retry_max_delay_seconds: float = 60.0
    tool_retry_jitter: bool = True
    recursion_limit: int = 9999


@dataclass(frozen=True)
class PersistenceSpec:
    backend: PersistenceBackend = "memory"
    database_url: str | None = None
    setup_on_start: bool = True

    def __post_init__(self) -> None:
        if self.backend == "postgres" and not self.database_url:
            raise ValueError("A postgres PersistenceSpec requires database_url.")


@dataclass(frozen=True)
class FilesystemPermissionSpec:
    """One declarative DeepAgents filesystem permission rule."""

    operations: tuple[FilesystemOperation, ...]
    paths: tuple[str, ...]
    mode: FilesystemPermissionMode = "allow"

    def as_deepagents_permission(self) -> dict[str, object]:
        return {
            "operations": list(self.operations),
            "paths": list(self.paths),
            "mode": self.mode,
        }


@dataclass(frozen=True)
class SandboxSpec:
    enabled: bool = False
    domain: str | None = None
    api_key: str | None = None
    protocol: str = "http"
    use_server_proxy: bool = False
    disable_metrics: bool = True
    image: str = "python:3.11"
    timeout_seconds: int | None = 600
    ready_timeout_seconds: int = 240
    cpu_limit: str = "250m"
    memory_limit: str = "256Mi"
    cpu_request: str = "100m"
    memory_request: str = "128Mi"
    scope: SandboxScope = "thread"
    max_active: int = 16
    workspace_path: str = "/workspace"
    internal_root: str = "/workspace/.ops-pilot"

    def __post_init__(self) -> None:
        if self.enabled and (not self.domain or not self.api_key):
            raise ValueError("An enabled SandboxSpec requires domain and api_key.")


@dataclass(frozen=True)
class ObservabilitySpec:
    environment: str = "local"
    public_key: str | None = None
    secret_key: str | None = None
    base_url: str | None = "https://cloud.langfuse.com"
    timeout_seconds: int = 30


@dataclass(frozen=True)
class RuntimeSpec:
    """Everything the host intentionally grants to one agent runtime."""

    id: str
    assistant_id: str
    entrypoint: str
    model: ModelSpec
    mcp: MCPServerCatalog = field(default_factory=MCPServerCatalog)
    system_prompt: str | None = None
    skills: tuple[Path, ...] = field(default_factory=tuple)
    memory: tuple[str, ...] = field(default_factory=tuple)
    permissions: tuple[FilesystemPermissionSpec, ...] = field(default_factory=tuple)
    filesystem_tools: tuple[str, ...] | None = None
    todo_list_enabled: bool = False
    interrupt_on: dict[str, bool] = field(default_factory=dict)
    debug: bool = False
    name: str | None = None
    reliability: ReliabilitySpec = field(default_factory=ReliabilitySpec)
    persistence: PersistenceSpec = field(default_factory=PersistenceSpec)
    sandbox: SandboxSpec = field(default_factory=SandboxSpec)
    observability: ObservabilitySpec = field(default_factory=ObservabilitySpec)
    extensions: tuple[RuntimeExtensionFactory, ...] = field(default_factory=tuple)
    tools: tuple[Any, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_tools(self, tools: Sequence[Any]) -> RuntimeSpec:
        return replace(self, tools=(*self.tools, *tools))
