"""Layered service settings: regular config from YAML, secrets from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.config.paths import REPO_ROOT, resolve_path

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"

SUPPORTED_MODEL_PROVIDERS = {"sap", "openai", "deepseek", "anthropic", "google_genai", "ollama"}

SUPPORTED_PERSISTENCE_BACKENDS = {"memory", "postgres"}


class SettingsError(RuntimeError):
    """Raised when regular configuration cannot be loaded."""


@dataclass(frozen=True)
class Settings:
    """Validated runtime settings consumed by backend modules.

    Regular (non-secret) values come from ``config/config.yaml``; secrets come
    from the process environment (``.env``).
    """

    app_env: str = "local"
    assistant_id: str = "agent"
    model_provider: str = "sap"
    model_base_url: str | None = None
    model_api_key: str | None = None
    sap_model_name: str = "anthropic--claude-4.6-sonnet"
    sap_temperature: float = 0.0
    sap_top_p: float | None = None
    sap_max_tokens: int | None = 16384
    model_request_timeout_seconds: int = 120
    model_reasoning_mode: str = "adaptive"
    model_reasoning_effort: str = "medium"
    system_prompt: str | None = None
    mcp: MCPConfig = field(default_factory=MCPConfig)
    skills_paths: tuple[Path, ...] = field(default_factory=tuple)
    enable_smoke_tools: bool = True
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str | None = "https://cloud.langfuse.com"
    chat_base_path: str = "/chat"
    chat_host: str = "127.0.0.1"
    chat_port: int = 8123
    a2a_base_path: str = "/a2a"
    persistence_backend: str = "memory"
    persistence_database_url: str | None = None
    persistence_setup_on_start: bool = True
    reliability_enabled: bool = True
    run_deadline_seconds: float | None = 600.0
    tool_retry_max_attempts: int = 3
    tool_retry_initial_backoff_seconds: float = 0.25
    tool_retry_backoff_multiplier: float = 2.0
    tool_retry_jitter_ratio: float = 0.2
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_seconds: float = 30.0
    chaos_flag_sync_timeout_seconds: float = 90.0
    chaos_poll_interval_seconds: float = 1.0
    chaos_stable_reads: int = 2
    open_sandbox_enabled: bool = False
    open_sandbox_domain: str | None = None
    open_sandbox_api_key: str | None = None
    open_sandbox_protocol: str = "https"
    open_sandbox_use_server_proxy: bool = True
    open_sandbox_disable_metrics: bool = True
    open_sandbox_image: str = "python:3.11"
    open_sandbox_timeout_seconds: int | None = 600
    open_sandbox_ready_timeout_seconds: int = 240
    open_sandbox_cpu_limit: str = "250m"
    open_sandbox_memory_limit: str = "256Mi"
    open_sandbox_cpu_request: str = "100m"
    open_sandbox_memory_request: str = "128Mi"
    open_sandbox_scope: str = "thread"
    open_sandbox_max_active: int = 16
    open_sandbox_workspace_path: str = "/workspace"
    open_sandbox_internal_root: str = "/workspace/.ops-pilot"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key and self.langfuse_base_url)

    @property
    def tracing_enabled(self) -> bool:
        return self.langfuse_enabled

    @property
    def sap_ai_core_model_name(self) -> str:
        return self.sap_model_name

    @property
    def model_name(self) -> str:
        """Provider-agnostic model name (aliases the historical sap field)."""

        return self.sap_model_name

    @property
    def uses_sap_ai_core(self) -> bool:
        return self.model_provider == "sap"

    @property
    def persistence_enabled(self) -> bool:
        """True when a durable (non-memory) persistence backend is configured."""

        return self.persistence_backend != "memory"

    def sqlalchemy_database_url(self) -> str | None:
        """Return the persistence URL normalized for SQLAlchemy async engines.

        LangGraph's ``AsyncPostgresSaver`` wants a psycopg (``postgresql://``)
        DSN, while the A2A ``DatabaseTaskStore`` uses a SQLAlchemy async engine
        that needs an explicit driver (``postgresql+asyncpg://``). We keep one
        URL in config and adapt it here for the SQLAlchemy consumer.
        """

        url = self.persistence_database_url
        if not url:
            return None
        if url.startswith("postgresql+"):
            return url
        if url.startswith("postgresql://"):
            return "postgresql+asyncpg://" + url[len("postgresql://") :]
        if url.startswith("postgres://"):
            return "postgresql+asyncpg://" + url[len("postgres://") :]
        return url

    def psycopg_database_url(self) -> str | None:
        """Return the persistence URL normalized for psycopg (``AsyncPostgresSaver``).

        psycopg rejects a SQLAlchemy-style ``+driver`` suffix, so strip it and
        normalize the legacy ``postgres://`` scheme to ``postgresql://``.
        """

        url = self.persistence_database_url
        if not url:
            return None
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        if url.startswith("postgresql+"):
            rest = url[len("postgresql") :]
            url = "postgresql" + rest[rest.index("://") :]
        return url

    def configured_system_prompt(self) -> str | None:
        if self.system_prompt and self.system_prompt.strip():
            return self.system_prompt.strip()
        return None

    def skill_path_values(self) -> list[str]:
        return [str(path) for path in self.skills_paths]


def load_settings(env: Mapping[str, str] | None = None, *, config: Mapping[str, Any] | None = None) -> Settings:
    """Load settings from ``config/config.yaml`` (regular) and the env (secrets).

    ``config`` lets callers (tests) inject a config mapping and skip the file
    read. ``env`` overrides the process environment for secret lookups.
    """

    if env is None:
        _load_dotenv()
    secret_source = os.environ if env is None else env
    config_data = config if config is not None else _load_config_file(secret_source)

    model = _section(config_data, "model")
    reasoning = _section(model, "reasoning")
    langfuse = _section(config_data, "langfuse")
    server = _section(config_data, "server")
    sandbox = _section(config_data, "open_sandbox")
    persistence = _section(config_data, "persistence")
    reliability = _section(config_data, "reliability")
    chaos = _section(config_data, "chaos")

    persistence_backend = _choice(
        persistence.get("backend"),
        default="memory",
        allowed=SUPPORTED_PERSISTENCE_BACKENDS,
        field_name="persistence.backend",
    )
    persistence_database_url = _optional_str(secret_source.get("DATABASE_URL"))
    if persistence_backend != "memory" and not persistence_database_url:
        raise SettingsError(
            f"persistence.backend is '{persistence_backend}' but DATABASE_URL is not set. "
            "Add DATABASE_URL to .env or set persistence.backend: memory."
        )

    open_sandbox_domain = _optional_str(sandbox.get("domain"))
    open_sandbox_api_key = _optional_str(secret_source.get("OPEN_SANDBOX_API_KEY"))
    open_sandbox_enabled = _optional_bool(sandbox.get("enabled"))
    if open_sandbox_enabled is None:
        open_sandbox_enabled = bool(open_sandbox_domain and open_sandbox_api_key)

    return Settings(
        app_env=_str(config_data.get("app_env"), "local"),
        assistant_id=_str(config_data.get("assistant_id"), "agent"),
        model_provider=_model_provider(model.get("provider")),
        model_base_url=_optional_str(model.get("base_url")),
        model_api_key=_optional_str(secret_source.get("MODEL_API_KEY")),
        sap_model_name=_str(model.get("model_name"), "anthropic--claude-4.6-sonnet"),
        sap_temperature=_float(model.get("temperature"), 0.0),
        sap_top_p=_optional_float(model.get("top_p")),
        sap_max_tokens=_optional_int(model.get("max_tokens")) or 16384,
        model_request_timeout_seconds=_positive_int(model.get("request_timeout_seconds"), 120),
        model_reasoning_mode=_choice(
            reasoning.get("mode"),
            default="adaptive",
            allowed={"adaptive", "disabled"},
            field_name="model.reasoning.mode",
        ),
        model_reasoning_effort=_choice(
            reasoning.get("effort"),
            default="medium",
            allowed={"low", "medium", "high"},
            field_name="model.reasoning.effort",
        ),
        system_prompt=_optional_str(config_data.get("system_prompt")),
        mcp=MCPConfig.from_mapping(config_data),
        skills_paths=tuple(resolve_path(path) for path in _str_list(config_data.get("skills_paths"))),
        enable_smoke_tools=_bool(config_data.get("enable_smoke_tools"), True),
        langfuse_public_key=_optional_str(secret_source.get("LANGFUSE_PUBLIC_KEY")),
        langfuse_secret_key=_optional_str(secret_source.get("LANGFUSE_SECRET_KEY")),
        langfuse_base_url=_optional_str(langfuse.get("base_url")),
        chat_base_path=_str(server.get("chat_base_path"), "/chat"),
        chat_host=_str(server.get("chat_host"), "127.0.0.1"),
        chat_port=_int(server.get("chat_port"), 8123),
        a2a_base_path=_str(server.get("a2a_base_path"), "/a2a"),
        persistence_backend=persistence_backend,
        persistence_database_url=persistence_database_url,
        persistence_setup_on_start=_bool(persistence.get("setup_on_start"), True),
        reliability_enabled=_bool(reliability.get("enabled"), True),
        run_deadline_seconds=_optional_positive_float(reliability.get("run_deadline_seconds"), 600.0),
        tool_retry_max_attempts=_positive_int(reliability.get("max_attempts"), 3),
        tool_retry_initial_backoff_seconds=_nonnegative_float(reliability.get("initial_backoff_seconds"), 0.25),
        tool_retry_backoff_multiplier=_positive_float(reliability.get("backoff_multiplier"), 2.0),
        tool_retry_jitter_ratio=_ratio(reliability.get("jitter_ratio"), 0.2),
        circuit_breaker_failure_threshold=_positive_int(reliability.get("failure_threshold"), 5),
        circuit_breaker_recovery_seconds=_positive_float(reliability.get("recovery_seconds"), 30.0),
        chaos_flag_sync_timeout_seconds=_positive_float(chaos.get("flag_sync_timeout_seconds"), 90.0),
        chaos_poll_interval_seconds=_positive_float(chaos.get("poll_interval_seconds"), 1.0),
        chaos_stable_reads=_positive_int(chaos.get("stable_reads"), 2),
        open_sandbox_enabled=open_sandbox_enabled,
        open_sandbox_domain=open_sandbox_domain,
        open_sandbox_api_key=open_sandbox_api_key,
        open_sandbox_protocol=_str(sandbox.get("protocol"), "https"),
        open_sandbox_use_server_proxy=_bool(sandbox.get("use_server_proxy"), True),
        open_sandbox_disable_metrics=_bool(sandbox.get("disable_metrics"), True),
        open_sandbox_image=_str(sandbox.get("image"), "python:3.11"),
        open_sandbox_timeout_seconds=_optional_int(sandbox.get("timeout_seconds")) or 600,
        open_sandbox_ready_timeout_seconds=_int(sandbox.get("ready_timeout_seconds"), 240),
        open_sandbox_cpu_limit=_str(sandbox.get("cpu_limit"), "250m"),
        open_sandbox_memory_limit=_str(sandbox.get("memory_limit"), "256Mi"),
        open_sandbox_cpu_request=_str(sandbox.get("cpu_request"), "100m"),
        open_sandbox_memory_request=_str(sandbox.get("memory_request"), "128Mi"),
        open_sandbox_scope=_sandbox_scope(sandbox.get("scope")),
        open_sandbox_max_active=_positive_int(sandbox.get("max_active"), 16),
        open_sandbox_workspace_path=_absolute_posix_path(sandbox.get("workspace_path"), "/workspace"),
        open_sandbox_internal_root=_absolute_posix_path(sandbox.get("internal_root"), "/workspace/.ops-pilot"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def _config_path(env: Mapping[str, str]) -> Path:
    override = env.get("OPS_PILOT_CONFIG", "").strip()
    if override:
        return resolve_path(override)
    return DEFAULT_CONFIG_PATH


def _load_config_file(env: Mapping[str, str]) -> Mapping[str, Any]:
    import yaml

    path = _config_path(env)
    if not path.exists():
        raise SettingsError(
            f"Config file not found: {path}. Copy config/config.example.yaml to "
            "config/config.yaml or set OPS_PILOT_CONFIG."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SettingsError(f"Config file is not valid YAML: {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise SettingsError(f"Config file root must be a mapping: {path}")
    return data


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(REPO_ROOT / ".env", override=False)


def _section(config: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = config.get(key)
    return value if isinstance(value, Mapping) else {}


def _str(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any, default: int) -> int:
    parsed = _optional_int(value)
    return parsed if parsed is not None else default


def _positive_int(value: Any, default: int) -> int:
    parsed = _int(value, default)
    if parsed < 1:
        raise SettingsError(f"Expected a positive integer, got: {value!r}")
    return parsed


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _positive_float(value: Any, default: float) -> float:
    parsed = _float(value, default)
    if parsed <= 0:
        raise SettingsError(f"Expected a positive number, got: {value!r}")
    return parsed


def _optional_positive_float(value: Any, default: float) -> float | None:
    if value is None:
        return default
    if value == "":
        return None
    return _positive_float(value, default)


def _nonnegative_float(value: Any, default: float) -> float:
    parsed = _float(value, default)
    if parsed < 0:
        raise SettingsError(f"Expected a non-negative number, got: {value!r}")
    return parsed


def _ratio(value: Any, default: float) -> float:
    parsed = _float(value, default)
    if not 0 <= parsed <= 1:
        raise SettingsError(f"Expected a ratio between 0 and 1, got: {value!r}")
    return parsed


def _bool(value: Any, default: bool) -> bool:
    parsed = _optional_bool(value)
    return parsed if parsed is not None else default


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise SettingsError(f"Expected a boolean value, got: {value!r}")


def _model_provider(value: Any) -> str:
    provider = _str(value, "sap").lower()
    if provider not in SUPPORTED_MODEL_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_MODEL_PROVIDERS))
        raise SettingsError(f"Expected model.provider to be one of {supported}; got: {value!r}")
    return provider


def _choice(value: Any, *, default: str, allowed: set[str], field_name: str) -> str:
    choice = _str(value, default).lower()
    if choice not in allowed:
        supported = ", ".join(sorted(allowed))
        raise SettingsError(f"Expected {field_name} to be one of {supported}; got: {value!r}")
    return choice


def _sandbox_scope(value: Any) -> str:
    scope = _str(value, "thread")
    if scope not in {"process", "thread", "run"}:
        raise SettingsError(f"Expected open_sandbox.scope to be one of process, thread, run; got: {value!r}")
    return scope


def _absolute_posix_path(value: Any, default: str) -> str:
    path = _str(value, default).rstrip("/") or "/"
    if not path.startswith("/") or "//" in path or "/../" in f"{path}/" or path.endswith("/.."):
        raise SettingsError(f"Expected an absolute POSIX path, got: {value!r}")
    return path


def _str_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        separator = "," if "," in value else os.pathsep
        return [part.strip() for part in value.split(separator) if part.strip()]
    if isinstance(value, list | tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    raise SettingsError(f"Expected a list of strings, got: {value!r}")
