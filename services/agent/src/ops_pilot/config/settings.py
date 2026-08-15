"""Typed service settings loaded from YAML with environment-backed secrets."""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from pydantic import AliasChoices, AliasPath, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

from ops_pilot.config.interpolation import expand_optional
from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.config.paths import REPO_ROOT, resolve_path

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"

PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
Ratio = Annotated[float, Field(ge=0, le=1)]
Port = Annotated[int, Field(ge=1, le=65535)]
ModelProvider = Literal["sap", "openai", "deepseek", "anthropic", "google_genai", "ollama"]
PersistenceBackend = Literal["memory", "postgres"]
ReasoningMode = Literal["adaptive", "disabled"]
ReasoningEffort = Literal["low", "medium", "high"]
SandboxScope = Literal["process", "thread", "run"]


class SettingsError(RuntimeError):
    """Raised when service configuration cannot be loaded or validated."""


def _alias(field_name: str, *path: str) -> AliasChoices:
    return AliasChoices(field_name, AliasPath(*path))


class Settings(BaseSettings):
    """Validated runtime settings consumed by backend modules."""

    model_config = SettingsConfigDict(
        extra="ignore",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    app_env: str = "local"
    assistant_id: str = "agent"
    model_provider: ModelProvider = Field("sap", validation_alias=_alias("model_provider", "model", "provider"))
    model_base_url: str | None = Field(None, validation_alias=_alias("model_base_url", "model", "base_url"))
    model_api_key: str | None = None
    model_name: str = Field(
        "anthropic--claude-4.6-sonnet",
        validation_alias=_alias("model_name", "model", "model_name"),
    )
    model_temperature: float = Field(0.0, validation_alias=_alias("model_temperature", "model", "temperature"))
    model_top_p: Ratio | None = Field(None, validation_alias=_alias("model_top_p", "model", "top_p"))
    model_max_tokens: PositiveInt | None = Field(
        16384,
        validation_alias=_alias("model_max_tokens", "model", "max_tokens"),
    )
    model_request_timeout_seconds: PositiveInt = Field(
        120,
        validation_alias=_alias("model_request_timeout_seconds", "model", "request_timeout_seconds"),
    )
    model_reasoning_mode: ReasoningMode = Field(
        "adaptive",
        validation_alias=_alias("model_reasoning_mode", "model", "reasoning", "mode"),
    )
    model_reasoning_effort: ReasoningEffort = Field(
        "medium",
        validation_alias=_alias("model_reasoning_effort", "model", "reasoning", "effort"),
    )
    system_prompt: str | None = None
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    skills_paths: tuple[Path, ...] = ()
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str | None = Field(
        "https://cloud.langfuse.com",
        validation_alias=_alias("langfuse_base_url", "langfuse", "base_url"),
    )
    langfuse_timeout_seconds: PositiveInt = Field(
        30,
        validation_alias=_alias("langfuse_timeout_seconds", "langfuse", "timeout_seconds"),
    )
    chat_base_path: str = Field("/chat", validation_alias=_alias("chat_base_path", "server", "chat_base_path"))
    chat_host: str = Field("127.0.0.1", validation_alias=_alias("chat_host", "server", "chat_host"))
    chat_port: Port = Field(8123, validation_alias=_alias("chat_port", "server", "chat_port"))
    a2a_base_path: str = Field("/a2a", validation_alias=_alias("a2a_base_path", "server", "a2a_base_path"))
    persistence_backend: PersistenceBackend = Field(
        "memory",
        validation_alias=_alias("persistence_backend", "persistence", "backend"),
    )
    persistence_database_url: str | None = None
    persistence_setup_on_start: bool = Field(
        True,
        validation_alias=_alias("persistence_setup_on_start", "persistence", "setup_on_start"),
    )
    spaces_resolver_enabled: bool = Field(
        True,
        validation_alias=_alias("spaces_resolver_enabled", "spaces", "resolver_enabled"),
    )
    spaces_resolver_poll_seconds: PositiveFloat = Field(
        30.0,
        validation_alias=_alias("spaces_resolver_poll_seconds", "spaces", "resolver_poll_seconds"),
    )
    reliability_enabled: bool = Field(
        True,
        validation_alias=_alias("reliability_enabled", "reliability", "enabled"),
    )
    run_deadline_seconds: PositiveFloat | None = Field(
        600.0,
        validation_alias=_alias("run_deadline_seconds", "reliability", "run_deadline_seconds"),
    )
    model_call_limit: PositiveInt = Field(
        50,
        validation_alias=_alias("model_call_limit", "reliability", "model_call_limit"),
    )
    tool_call_limit: PositiveInt = Field(
        200,
        validation_alias=_alias("tool_call_limit", "reliability", "tool_call_limit"),
    )
    tool_retry_max_retries: NonNegativeInt = Field(
        2,
        validation_alias=_alias("tool_retry_max_retries", "reliability", "tool_retry_max_retries"),
    )
    tool_retry_initial_delay_seconds: NonNegativeFloat = Field(
        0.25,
        validation_alias=_alias(
            "tool_retry_initial_delay_seconds",
            "reliability",
            "tool_retry_initial_delay_seconds",
        ),
    )
    tool_retry_backoff_factor: PositiveFloat = Field(
        2.0,
        validation_alias=_alias("tool_retry_backoff_factor", "reliability", "tool_retry_backoff_factor"),
    )
    tool_retry_max_delay_seconds: PositiveFloat = Field(
        60.0,
        validation_alias=_alias("tool_retry_max_delay_seconds", "reliability", "tool_retry_max_delay_seconds"),
    )
    tool_retry_jitter: bool = Field(
        True,
        validation_alias=_alias("tool_retry_jitter", "reliability", "tool_retry_jitter"),
    )
    chaos_namespace: str = Field("otel-demo", validation_alias=_alias("chaos_namespace", "chaos", "namespace"))
    chaos_flagd_service: str = Field(
        "flagd",
        validation_alias=_alias("chaos_flagd_service", "chaos", "flagd_service"),
    )
    chaos_flagd_service_port: Port = Field(
        8016,
        validation_alias=_alias("chaos_flagd_service_port", "chaos", "flagd_service_port"),
    )
    chaos_flagd_ui_port: Port = Field(
        4000,
        validation_alias=_alias("chaos_flagd_ui_port", "chaos", "flagd_ui_port"),
    )
    chaos_flag_sync_timeout_seconds: PositiveFloat = Field(
        90.0,
        validation_alias=_alias("chaos_flag_sync_timeout_seconds", "chaos", "flag_sync_timeout_seconds"),
    )
    chaos_poll_interval_seconds: PositiveFloat = Field(
        1.0,
        validation_alias=_alias("chaos_poll_interval_seconds", "chaos", "poll_interval_seconds"),
    )
    chaos_stable_reads: PositiveInt = Field(
        2,
        validation_alias=_alias("chaos_stable_reads", "chaos", "stable_reads"),
    )
    chaos_signal_warmup_seconds: NonNegativeFloat = Field(
        15.0,
        validation_alias=_alias("chaos_signal_warmup_seconds", "chaos", "signal_warmup_seconds"),
    )
    open_sandbox_enabled: bool = False
    open_sandbox_domain: str | None = None
    open_sandbox_api_key: str | None = None
    open_sandbox_protocol: str = Field(
        "https",
        validation_alias=_alias("open_sandbox_protocol", "open_sandbox", "protocol"),
    )
    open_sandbox_use_server_proxy: bool = Field(
        True,
        validation_alias=_alias("open_sandbox_use_server_proxy", "open_sandbox", "use_server_proxy"),
    )
    open_sandbox_disable_metrics: bool = Field(
        True,
        validation_alias=_alias("open_sandbox_disable_metrics", "open_sandbox", "disable_metrics"),
    )
    open_sandbox_image: str = Field(
        "python:3.11",
        validation_alias=_alias("open_sandbox_image", "open_sandbox", "image"),
    )
    open_sandbox_timeout_seconds: PositiveInt | None = Field(
        600,
        validation_alias=_alias("open_sandbox_timeout_seconds", "open_sandbox", "timeout_seconds"),
    )
    open_sandbox_ready_timeout_seconds: PositiveInt = Field(
        240,
        validation_alias=_alias("open_sandbox_ready_timeout_seconds", "open_sandbox", "ready_timeout_seconds"),
    )
    open_sandbox_cpu_limit: str = Field(
        "250m",
        validation_alias=_alias("open_sandbox_cpu_limit", "open_sandbox", "cpu_limit"),
    )
    open_sandbox_memory_limit: str = Field(
        "256Mi",
        validation_alias=_alias("open_sandbox_memory_limit", "open_sandbox", "memory_limit"),
    )
    open_sandbox_cpu_request: str = Field(
        "100m",
        validation_alias=_alias("open_sandbox_cpu_request", "open_sandbox", "cpu_request"),
    )
    open_sandbox_memory_request: str = Field(
        "128Mi",
        validation_alias=_alias("open_sandbox_memory_request", "open_sandbox", "memory_request"),
    )
    open_sandbox_scope: SandboxScope = Field(
        "thread",
        validation_alias=_alias("open_sandbox_scope", "open_sandbox", "scope"),
    )
    open_sandbox_max_active: PositiveInt = Field(
        16,
        validation_alias=_alias("open_sandbox_max_active", "open_sandbox", "max_active"),
    )
    open_sandbox_workspace_path: str = Field(
        "/workspace",
        validation_alias=_alias("open_sandbox_workspace_path", "open_sandbox", "workspace_path"),
    )
    open_sandbox_internal_root: str = Field(
        "/workspace/.ops-pilot",
        validation_alias=_alias("open_sandbox_internal_root", "open_sandbox", "internal_root"),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del settings_cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings,)

    @field_validator("skills_paths", mode="after")
    @classmethod
    def _resolve_skill_paths(cls, paths: tuple[Path, ...]) -> tuple[Path, ...]:
        return tuple(resolve_path(path) for path in paths)

    @field_validator("system_prompt", mode="after")
    @classmethod
    def _empty_prompt_is_unset(cls, prompt: str | None) -> str | None:
        return prompt or None

    @field_validator("open_sandbox_workspace_path", "open_sandbox_internal_root")
    @classmethod
    def _validate_absolute_posix_path(cls, path: str) -> str:
        normalized = path.rstrip("/") or "/"
        if not normalized.startswith("/") or "//" in normalized or "/../" in f"{normalized}/":
            raise ValueError("must be an absolute POSIX path without parent traversal")
        return normalized

    @model_validator(mode="after")
    def _require_database_url(self) -> Settings:
        if self.persistence_backend == "postgres" and not self.persistence_database_url:
            raise ValueError(
                "persistence.backend is 'postgres' but DATABASE_URL is not set. "
                "Add DATABASE_URL to .env or set persistence.backend: memory."
            )
        return self

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key and self.langfuse_base_url)

    def sqlalchemy_database_url(self) -> str | None:
        url = self.persistence_database_url
        if not url:
            return None
        if url.startswith("postgresql+"):
            normalized = url
        elif url.startswith("postgresql://"):
            normalized = "postgresql+asyncpg://" + url[len("postgresql://") :]
        else:
            return url
        return _rename_url_query_parameter(normalized, source="sslmode", target="ssl")

    def psycopg_database_url(self) -> str | None:
        url = self.persistence_database_url
        if not url or not url.startswith("postgresql+"):
            return url
        rest = url[len("postgresql") :]
        return "postgresql" + rest[rest.index("://") :]


class _Environment(BaseSettings):
    """Environment-only values; regular configuration remains YAML-owned."""

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    config_path: Path | None = Field(None, validation_alias="OPS_PILOT_CONFIG")
    model_api_key: str | None = Field(None, validation_alias="MODEL_API_KEY")
    langfuse_public_key: str | None = Field(None, validation_alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str | None = Field(None, validation_alias="LANGFUSE_SECRET_KEY")
    persistence_database_url: str | None = Field(None, validation_alias="DATABASE_URL")
    open_sandbox_api_key: str | None = Field(None, validation_alias="OPEN_SANDBOX_API_KEY")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del settings_cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings,)


def _rename_url_query_parameter(url: str, *, source: str, target: str) -> str:
    parsed = urlsplit(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    source_values = [value for key, value in query if key == source]
    if not source_values:
        return url
    without_source = [(key, value) for key, value in query if key != source]
    if not any(key == target for key, _ in without_source):
        without_source.append((target, source_values[-1]))
    return urlunsplit(parsed._replace(query=urlencode(without_source)))


def load_settings(env: Mapping[str, str] | None = None, *, config: Mapping[str, Any] | None = None) -> Settings:
    """Load regular YAML configuration and overlay environment-backed secrets."""

    if env is None:
        load_dotenv(REPO_ROOT / ".env", override=False)
        environment_values: Mapping[str, str] = os.environ
    else:
        environment_values = env
    environment = _Environment.model_validate(environment_values)

    config_data = dict(config) if config is not None else _load_config_file(environment.config_path)
    sandbox = config_data.get("open_sandbox")
    sandbox_data = dict(sandbox) if isinstance(sandbox, Mapping) else {}
    sandbox_domain = expand_optional(sandbox_data.get("domain"), environment_values)
    sandbox_enabled = sandbox_data.get("enabled")

    values = {
        **config_data,
        "mcp": MCPConfig.from_mapping(config_data, env=environment_values),
        "model_api_key": environment.model_api_key,
        "langfuse_public_key": environment.langfuse_public_key,
        "langfuse_secret_key": environment.langfuse_secret_key,
        "persistence_database_url": environment.persistence_database_url,
        "open_sandbox_api_key": environment.open_sandbox_api_key,
        "open_sandbox_domain": sandbox_domain,
        "open_sandbox_enabled": (
            bool(sandbox_domain and environment.open_sandbox_api_key) if sandbox_enabled is None else sandbox_enabled
        ),
    }
    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        raise SettingsError(str(exc)) from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def _load_config_file(path: Path | None) -> dict[str, Any]:
    resolved = resolve_path(path or DEFAULT_CONFIG_PATH)
    if not resolved.exists():
        raise SettingsError(
            f"Config file not found: {resolved}. Copy config/config.example.yaml to "
            "config/config.yaml or set OPS_PILOT_CONFIG."
        )
    try:
        return dict(YamlConfigSettingsSource(Settings, yaml_file=resolved, yaml_file_encoding="utf-8")())
    except Exception as exc:
        raise SettingsError(f"Config file is not valid YAML: {resolved}: {exc}") from exc
