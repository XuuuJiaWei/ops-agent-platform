"""Entrypoint-local runtime configuration and environment-only secrets."""

from __future__ import annotations

from typing import Literal

from dotenv import load_dotenv
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from ops_pilot.config.paths import REPO_ROOT
from ops_pilot.runtime.spec import ModelProvider, PersistenceBackend, ReasoningEffort, ReasoningMode, SandboxScope

ENTRYPOINT_CONFIG_DIR = REPO_ROOT / "config" / "entries"


def _kebab_case(name: str) -> str:
    return name.replace("_", "-")


_SECRET_FIELD_NAMES = frozenset(
    {
        "api-key",
        "public-key",
        "secret-key",
        "database-url",
        "basic-auth-header",
    }
)
_SECRET_SETTINGS_FIELD_NAMES = frozenset(
    {
        "model_api_key",
        "langfuse_public_key",
        "langfuse_secret_key",
        "database_url",
        "open_sandbox_api_key",
        "mcp_basic_auth_header",
    }
)
_SECRET_SOURCE_FIELD_NAMES = _SECRET_SETTINGS_FIELD_NAMES | frozenset(
    {
        "MODEL_API_KEY",
        "OPENROUTER_API_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "DATABASE_URL",
        "OPEN_SANDBOX_API_KEY",
        "MCP_BASIC_AUTH_HEADER",
    }
)
_SHARED_MODEL_CONFIG = {
    "env_file": REPO_ROOT / ".env",
    "env_file_encoding": "utf-8",
    "env_ignore_empty": True,
    "env_prefix": "OPS_PILOT_SECRET_",
    # The shared .env also contains credentials consumed directly by SAP and
    # deployment tooling. This settings model intentionally selects only its
    # explicit aliases from that file.
    "extra": "ignore",
    "frozen": True,
    "yaml_file_encoding": "utf-8",
}

FilesystemTool = Literal["ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "execute"]
FilesystemOperation = Literal["read", "write"]
FilesystemPermissionMode = Literal["allow", "deny", "interrupt"]
BackendType = Literal["state", "opensandbox"]


class _RuntimeConfiguration(BaseModel):
    """Strict nested schema for non-sensitive entrypoint YAML."""

    model_config = ConfigDict(alias_generator=_kebab_case, populate_by_name=True, extra="forbid", frozen=True)


class ReasoningConfiguration(_RuntimeConfiguration):
    mode: ReasoningMode = "adaptive"
    effort: ReasoningEffort = "medium"


class ModelConfiguration(_RuntimeConfiguration):
    provider: ModelProvider = "sap"
    name: str = "anthropic--claude-4.6-sonnet"
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 16384
    timeout_seconds: int = 120
    reasoning: ReasoningConfiguration = Field(default_factory=ReasoningConfiguration)


class KubernetesMCPConfiguration(_RuntimeConfiguration):
    kubeconfig: str | None = None
    read_timeout_seconds: int = 60


class HTTPMCPConfiguration(_RuntimeConfiguration):
    url: str | None = None
    timeout_seconds: int = 90
    read_timeout_seconds: int = 30
    retry_tools: tuple[str, ...] = ()


class MCPToolConfiguration(_RuntimeConfiguration):
    kubernetes: KubernetesMCPConfiguration = Field(default_factory=KubernetesMCPConfiguration)
    jaeger: HTTPMCPConfiguration = Field(
        default_factory=lambda: HTTPMCPConfiguration(retry_tools=("search_traces", "get_services", "get_span_details"))
    )
    prometheus: HTTPMCPConfiguration = Field(default_factory=HTTPMCPConfiguration)


class ToolsConfiguration(_RuntimeConfiguration):
    """The ``tools=`` capability catalog for this host.

    Frontend-only CopilotKit tools deliberately do not belong here. They are
    React declarations, while this schema declares backend MCP capabilities.
    """

    mcp: MCPToolConfiguration = Field(default_factory=MCPToolConfiguration)


class FilesystemConfiguration(_RuntimeConfiguration):
    """The official ``FilesystemMiddleware`` allowlist.

    A null value preserves DeepAgents' default filesystem tool surface. A
    concrete list becomes the middleware's model-visible allowlist.
    """

    tools: tuple[FilesystemTool, ...] | None = None


class ReliabilityMiddlewareConfiguration(_RuntimeConfiguration):
    enabled: bool = True
    run_deadline_seconds: float = 600
    model_call_limit: int = 50
    tool_call_limit: int = 200


class MiddlewareConfiguration(_RuntimeConfiguration):
    """Agent middleware selected by the entrypoint."""

    todo_list: bool = False
    filesystem: FilesystemConfiguration = Field(default_factory=FilesystemConfiguration)
    reliability: ReliabilityMiddlewareConfiguration = Field(default_factory=ReliabilityMiddlewareConfiguration)


class FilesystemPermissionConfiguration(_RuntimeConfiguration):
    operations: tuple[FilesystemOperation, ...]
    paths: tuple[str, ...]
    mode: FilesystemPermissionMode = "allow"


class OpenSandboxConfiguration(_RuntimeConfiguration):
    domain: str | None = None
    protocol: str = "http"
    use_server_proxy: bool = False
    image: str = "python:3.11"
    timeout_seconds: int = 600
    ready_timeout_seconds: int = 240
    scope: SandboxScope = "thread"


class BackendConfiguration(_RuntimeConfiguration):
    """The ``backend=`` choice for DeepAgents' virtual filesystem/runtime."""

    type: BackendType = "state"
    opensandbox: OpenSandboxConfiguration = Field(default_factory=OpenSandboxConfiguration)


class CheckpointerConfiguration(_RuntimeConfiguration):
    """The ``checkpointer=`` runtime persistence selection."""

    backend: PersistenceBackend = "memory"
    setup_on_start: bool = True


class LangfuseConfiguration(_RuntimeConfiguration):
    base_url: str = "https://cloud.langfuse.com"
    timeout_seconds: int = 30


class ObservabilityConfiguration(_RuntimeConfiguration):
    enabled: bool = False
    environment: str = "local"
    langfuse: LangfuseConfiguration = Field(default_factory=LangfuseConfiguration)


class ChatServerConfiguration(_RuntimeConfiguration):
    base_path: str = "/chat"


class A2AServerConfiguration(_RuntimeConfiguration):
    base_path: str = "/a2a"
    enabled: bool = True


class ServerConfiguration(_RuntimeConfiguration):
    host: str = "127.0.0.1"
    port: int = 8123
    chat: ChatServerConfiguration = Field(default_factory=ChatServerConfiguration)
    a2a: A2AServerConfiguration = Field(default_factory=A2AServerConfiguration)


class SpacesConfiguration(_RuntimeConfiguration):
    enabled: bool = True


class FrontendConfiguration(_RuntimeConfiguration):
    port: int = 3000


class CopilotRuntimeConfiguration(_RuntimeConfiguration):
    host: str = "127.0.0.1"
    port: int = 4001
    base_path: str = "/api/copilotkit"
    event_store_backend: PersistenceBackend = "memory"
    event_store_setup_on_start: bool = True


class WebSurfaceConfiguration(_RuntimeConfiguration):
    spaces: SpacesConfiguration = Field(default_factory=SpacesConfiguration)
    frontend: FrontendConfiguration = Field(default_factory=FrontendConfiguration)
    copilot_runtime: CopilotRuntimeConfiguration = Field(default_factory=CopilotRuntimeConfiguration)


class AIOpsLabConfiguration(_RuntimeConfiguration):
    directory: str | None = None


class BenchmarkConfiguration(_RuntimeConfiguration):
    aiopslab: AIOpsLabConfiguration = Field(default_factory=AIOpsLabConfiguration)


class DeepAgentConfiguration(_RuntimeConfiguration):
    """The complete declarative harness passed to ``create_deep_agent``."""

    model: ModelConfiguration = Field(default_factory=ModelConfiguration)
    tools: ToolsConfiguration = Field(default_factory=ToolsConfiguration)
    system_prompt: str | None = None
    middleware: MiddlewareConfiguration = Field(default_factory=MiddlewareConfiguration)
    skills: tuple[str, ...] = ("skills",)
    memory: tuple[str, ...] = ()
    permissions: tuple[FilesystemPermissionConfiguration, ...] = ()
    backend: BackendConfiguration = Field(default_factory=BackendConfiguration)
    interrupt_on: dict[str, bool] = Field(default_factory=dict)
    checkpointer: CheckpointerConfiguration = Field(default_factory=CheckpointerConfiguration)
    debug: bool = False
    name: str | None = None


def _declared_secret_paths(value: object, path: tuple[str, ...] = ()) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    found: list[str] = []
    for key, nested_value in value.items():
        normalized_key = str(key).replace("_", "-")
        nested_path = (*path, str(key))
        if normalized_key in _SECRET_FIELD_NAMES:
            found.append(".".join(nested_path))
        found.extend(_declared_secret_paths(nested_value, nested_path))
    return tuple(found)


class _EntrypointYamlSource(YamlConfigSettingsSource):
    """Reject credentials in a declarative runtime composition file."""

    def __call__(self) -> dict[str, object]:
        values = super().__call__()
        known_fields = set(self.settings_cls.model_fields) | {
            _kebab_case(name) for name in self.settings_cls.model_fields
        }
        unknown_fields = set(values).difference(known_fields)
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Unknown entrypoint YAML fields: {names}")
        declared_secrets = _declared_secret_paths(values)
        if declared_secrets:
            names = ", ".join(sorted(declared_secrets))
            raise ValueError(f"Secrets must be supplied through .env, not an entrypoint YAML file: {names}")
        return {
            key if key in self.settings_cls.model_fields else str(key).replace("-", "_"): value
            for key, value in values.items()
        }


class _SecretOnlyEnvironmentSource(EnvSettingsSource):
    """Allow process environment input only for explicit credential fields."""

    def __call__(self) -> dict[str, object]:
        return {name: value for name, value in super().__call__().items() if name in _SECRET_SOURCE_FIELD_NAMES}


class _SecretOnlyDotenvSource(DotEnvSettingsSource):
    """Allow `.env` input only for explicit credential fields."""

    def __call__(self) -> dict[str, object]:
        return {name: value for name, value in super().__call__().items() if name in _SECRET_SOURCE_FIELD_NAMES}


class RuntimeEnvironment(BaseSettings):
    """Validated values for one complete, nested runtime composition.

    ``deepagent`` holds the official ``create_deep_agent`` injection points.
    Sibling keys describe the process host (server, web, benchmark) or tracing.
    Credentials use explicit aliases in `.env` only.
    """

    model_config = SettingsConfigDict(**_SHARED_MODEL_CONFIG, yaml_file=None)

    deepagent: DeepAgentConfiguration = Field(default_factory=DeepAgentConfiguration)
    observability: ObservabilityConfiguration = Field(default_factory=ObservabilityConfiguration)
    server: ServerConfiguration = Field(default_factory=ServerConfiguration)
    web: WebSurfaceConfiguration = Field(default_factory=WebSurfaceConfiguration)
    benchmark: BenchmarkConfiguration = Field(default_factory=BenchmarkConfiguration)

    # Secrets are deliberately not part of the YAML tree.
    model_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "MODEL_API_KEY"),
    )
    langfuse_public_key: str | None = Field(default=None, validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY"))
    langfuse_secret_key: str | None = Field(default=None, validation_alias=AliasChoices("LANGFUSE_SECRET_KEY"))
    database_url: str | None = Field(default=None, validation_alias=AliasChoices("DATABASE_URL"))
    open_sandbox_api_key: str | None = Field(default=None, validation_alias=AliasChoices("OPEN_SANDBOX_API_KEY"))
    mcp_basic_auth_header: str | None = Field(default=None, validation_alias=AliasChoices("MCP_BASIC_AUTH_HEADER"))

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _SecretOnlyEnvironmentSource(settings_cls),
            _SecretOnlyDotenvSource(settings_cls),
            _EntrypointYamlSource(settings_cls),
            file_secret_settings,
        )

    @classmethod
    def for_entrypoint(cls, name: str) -> RuntimeEnvironment:
        """Load one named composition from `config/entries/<name>.yaml`."""

        load_dotenv(REPO_ROOT / ".env", override=False)
        try:
            environment_type = _ENTRYPOINT_ENVIRONMENTS[name]
        except KeyError as exc:
            known = ", ".join(sorted(_ENTRYPOINT_ENVIRONMENTS))
            raise ValueError(f"Unknown runtime entrypoint {name!r}. Expected one of: {known}.") from exc
        return environment_type()


def _entrypoint_environment(name: str) -> type[RuntimeEnvironment]:
    return type(
        f"{name.title()}RuntimeEnvironment",
        (RuntimeEnvironment,),
        {
            "model_config": SettingsConfigDict(
                **_SHARED_MODEL_CONFIG,
                yaml_file=ENTRYPOINT_CONFIG_DIR / f"{name}.yaml",
            )
        },
    )


_ENTRYPOINT_ENVIRONMENTS: dict[str, type[RuntimeEnvironment]] = {
    name: _entrypoint_environment(name) for name in ("web", "eval", "benchmark", "langgraph")
}
