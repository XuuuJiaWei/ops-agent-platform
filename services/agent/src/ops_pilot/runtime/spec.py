"""Host-neutral declarations for assembling one DeepAgents runtime.

An entrypoint owns a :class:`RuntimeSpec`.  The core runtime only consumes this
already-declared composition; it never discovers a global configuration file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from ops_pilot.mcp.spec import MCPServerCatalog

ModelProvider = Literal["sap", "openai", "deepseek", "anthropic", "google_genai", "ollama"]
PersistenceBackend = Literal["memory", "postgres", "none"]
SandboxScope = Literal["process", "thread", "run"]
ReasoningMode = Literal["adaptive", "disabled"]
ReasoningEffort = Literal["low", "medium", "high"]
AgentLogPayloads = Literal["metadata", "preview"]
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
    enabled: bool = False
    run_deadline_seconds: float | None = 600.0
    model_call_limit: int = 50
    tool_call_limit: int = 200
    tool_retry_max_retries: int = 2
    tool_retry_initial_delay_seconds: float = 0.25
    tool_retry_backoff_factor: float = 2.0
    tool_retry_max_delay_seconds: float = 60.0
    tool_retry_jitter: bool = True
    recursion_limit: int = 256


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
class AgentLoggingSpec:
    enabled: bool = False
    level: str = "INFO"
    payloads: AgentLogPayloads = "metadata"
    max_preview_chars: int = 500


@dataclass(frozen=True)
class ObservabilitySpec:
    enabled: bool = False
    environment: str = "local"
    public_key: str | None = None
    secret_key: str | None = None
    base_url: str | None = "https://cloud.langfuse.com"
    timeout_seconds: int = 30
    logging: AgentLoggingSpec = field(default_factory=AgentLoggingSpec)


@dataclass(frozen=True)
class RuntimeSpec:
    """Everything the host intentionally grants to one agent runtime.

    Runtime objects injected through tools, middleware, backend, store, cache,
    and subagents remain owned by the host that created them. The harness owns
    only resources it constructs from declarative specs such as persistence
    and sandbox configuration.
    """

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
    tools: tuple[Any, ...] = field(default_factory=tuple)
    middleware: tuple[Any, ...] = field(default_factory=tuple)
    context_schema: type[Any] | None = None
    state_schema: type[Any] | None = None
    response_format: Any | None = None
    backend: Any | None = None
    store: Any | None = None
    cache: Any | None = None
    subagents: tuple[Any, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_tools(self, tools: Sequence[Any]) -> RuntimeSpec:
        return replace(self, tools=(*self.tools, *tools))

    def with_middleware(self, middleware: Sequence[Any]) -> RuntimeSpec:
        return replace(self, middleware=(*self.middleware, *middleware))
