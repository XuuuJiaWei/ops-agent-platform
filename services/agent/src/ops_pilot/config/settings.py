"""Environment-backed service settings."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ops_pilot.config.paths import REPO_ROOT, resolve_path


def _env_text(env: Mapping[str, str], key: str, default: str = "") -> str:
    return env.get(key, default).strip()


def _optional_text(env: Mapping[str, str], key: str) -> str | None:
    value = _env_text(env, key)
    return value or None


def _optional_int(env: Mapping[str, str], key: str) -> int | None:
    value = _optional_text(env, key)
    return int(value) if value is not None else None


def _optional_bool(env: Mapping[str, str], key: str) -> bool | None:
    value = _optional_text(env, key)
    if value is None:
        return None
    normalized = value.lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ValueError(f"{key} must be a boolean value")


def _split_paths(value: str) -> list[str]:
    if not value.strip():
        return []
    separator = "," if "," in value else os.pathsep
    return [part.strip() for part in value.split(separator) if part.strip()]


@dataclass(frozen=True)
class Settings:
    """Validated runtime settings consumed by backend modules."""

    app_env: str = "local"
    assistant_id: str = "agent"
    sap_model_name: str = "anthropic--claude-4.6-sonnet"
    sap_temperature: float = 0.0
    sap_top_p: float | None = None
    sap_max_tokens: int | None = 8192
    system_prompt: str | None = None
    mcp_config_path: Path | None = None
    skills_paths: tuple[Path, ...] = field(default_factory=tuple)
    enable_smoke_tools: bool = True
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str | None = "https://cloud.langfuse.com"
    chat_base_path: str = "/chat"
    chat_host: str = "127.0.0.1"
    chat_port: int = 8123
    a2a_base_path: str = "/a2a"
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

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key and self.langfuse_base_url)

    @property
    def tracing_enabled(self) -> bool:
        return self.langfuse_enabled

    @property
    def sap_ai_core_model_name(self) -> str:
        return self.sap_model_name

    def configured_system_prompt(self) -> str | None:
        if self.system_prompt and self.system_prompt.strip():
            return self.system_prompt.strip()
        return None

    def skill_path_values(self) -> list[str]:
        return [str(path) for path in self.skills_paths]


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Load settings from environment variables without importing integrations."""

    if env is None:
        _load_dotenv()
    source = os.environ if env is None else env
    mcp_config = _optional_text(source, "MCP_CONFIG_PATH")
    skill_paths = tuple(resolve_path(path) for path in _split_paths(source.get("SKILLS_PATHS", "")))
    open_sandbox_domain = _optional_text(source, "OPEN_SANDBOX_DOMAIN")
    open_sandbox_api_key = _optional_text(source, "OPEN_SANDBOX_API_KEY")
    open_sandbox_enabled = _optional_bool(source, "OPEN_SANDBOX_ENABLED")
    open_sandbox_use_server_proxy = _optional_bool(source, "OPEN_SANDBOX_USE_SERVER_PROXY")
    open_sandbox_disable_metrics = _optional_bool(source, "OPEN_SANDBOX_DISABLE_METRICS")
    if open_sandbox_enabled is None:
        open_sandbox_enabled = bool(open_sandbox_domain and open_sandbox_api_key)

    return Settings(
        app_env=_env_text(source, "APP_ENV", "local") or "local",
        assistant_id=_env_text(source, "ASSISTANT_ID", "agent") or "agent",
        sap_model_name=_env_text(source, "SAP_AI_CORE_MODEL_NAME", "anthropic--claude-4.6-sonnet")
        or "anthropic--claude-4.6-sonnet",
        sap_max_tokens=_optional_int(source, "SAP_AI_CORE_MAX_TOKENS") or 8192,
        system_prompt=_optional_text(source, "SYSTEM_PROMPT"),
        mcp_config_path=resolve_path(mcp_config) if mcp_config else None,
        skills_paths=skill_paths,
        langfuse_public_key=_optional_text(source, "LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key=_optional_text(source, "LANGFUSE_SECRET_KEY"),
        langfuse_base_url=_optional_text(source, "LANGFUSE_BASE_URL"),
        chat_host=_env_text(source, "CHAT_HOST", "127.0.0.1") or "127.0.0.1",
        chat_port=int(_env_text(source, "CHAT_PORT", "8123") or "8123"),
        open_sandbox_enabled=open_sandbox_enabled,
        open_sandbox_domain=open_sandbox_domain,
        open_sandbox_api_key=open_sandbox_api_key,
        open_sandbox_protocol=_env_text(source, "OPEN_SANDBOX_PROTOCOL", "https") or "https",
        open_sandbox_use_server_proxy=open_sandbox_use_server_proxy
        if open_sandbox_use_server_proxy is not None
        else True,
        open_sandbox_disable_metrics=open_sandbox_disable_metrics if open_sandbox_disable_metrics is not None else True,
        open_sandbox_image=_env_text(source, "OPEN_SANDBOX_IMAGE", "python:3.11") or "python:3.11",
        open_sandbox_timeout_seconds=_optional_int(source, "OPEN_SANDBOX_TIMEOUT_SECONDS") or 600,
        open_sandbox_ready_timeout_seconds=_optional_int(source, "OPEN_SANDBOX_READY_TIMEOUT_SECONDS") or 240,
        open_sandbox_cpu_limit=_env_text(source, "OPEN_SANDBOX_CPU_LIMIT", "250m") or "250m",
        open_sandbox_memory_limit=_env_text(source, "OPEN_SANDBOX_MEMORY_LIMIT", "256Mi") or "256Mi",
        open_sandbox_cpu_request=_env_text(source, "OPEN_SANDBOX_CPU_REQUEST", "100m") or "100m",
        open_sandbox_memory_request=_env_text(source, "OPEN_SANDBOX_MEMORY_REQUEST", "128Mi") or "128Mi",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(REPO_ROOT / ".env", override=False)
