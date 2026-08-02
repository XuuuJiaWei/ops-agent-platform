"""Environment-backed service settings."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ops_pilot.config.paths import REPO_ROOT, resolve_path

TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def _env_text(env: Mapping[str, str], key: str, default: str = "") -> str:
    return env.get(key, default).strip()


def _optional_text(env: Mapping[str, str], key: str) -> str | None:
    value = _env_text(env, key)
    return value or None


def _optional_float(env: Mapping[str, str], key: str) -> float | None:
    value = _optional_text(env, key)
    return float(value) if value is not None else None


def _optional_int(env: Mapping[str, str], key: str) -> int | None:
    value = _optional_text(env, key)
    return int(value) if value is not None else None


def _env_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in TRUE_VALUES


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
    enable_dynatrace_dashboard: bool = True
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str | None = "https://cloud.langfuse.com"
    chat_base_path: str = "/chat"
    chat_host: str = "127.0.0.1"
    chat_port: int = 8123
    a2a_base_path: str = "/a2a"
    a2a_task_store: str = "memory"
    a2a_host: str = "127.0.0.1"
    a2a_port: int = 41241

    @property
    def langfuse_enabled(self) -> bool:
        return bool(
            self.langfuse_public_key and self.langfuse_secret_key and self.langfuse_base_url
        )

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

    return Settings(
        app_env=_env_text(source, "APP_ENV", "local") or "local",
        assistant_id=_env_text(source, "ASSISTANT_ID", "agent") or "agent",
        sap_model_name=_env_text(source, "SAP_AI_CORE_MODEL_NAME", "anthropic--claude-4.6-sonnet")
        or "anthropic--claude-4.6-sonnet",
        sap_temperature=float(_env_text(source, "SAP_AI_CORE_TEMPERATURE", "0") or "0"),
        sap_top_p=_optional_float(source, "SAP_AI_CORE_TOP_P"),
        sap_max_tokens=_optional_int(source, "SAP_AI_CORE_MAX_TOKENS") or 8192,
        system_prompt=_optional_text(source, "SYSTEM_PROMPT"),
        mcp_config_path=resolve_path(mcp_config) if mcp_config else None,
        skills_paths=skill_paths,
        enable_smoke_tools=_env_bool(source, "ENABLE_SMOKE_TOOLS", True),
        enable_dynatrace_dashboard=_env_bool(source, "ENABLE_DYNATRACE_DASHBOARD", True),
        langfuse_public_key=_optional_text(source, "LANGFUSE_PUBLIC_KEY"),
        langfuse_secret_key=_optional_text(source, "LANGFUSE_SECRET_KEY"),
        langfuse_base_url=_optional_text(source, "LANGFUSE_BASE_URL"),
        chat_base_path=_env_text(source, "CHAT_BASE_PATH", "/chat") or "/chat",
        chat_host=_env_text(source, "CHAT_HOST", "127.0.0.1") or "127.0.0.1",
        chat_port=int(_env_text(source, "CHAT_PORT", "8123") or "8123"),
        a2a_base_path=_env_text(source, "A2A_BASE_PATH", "/a2a") or "/a2a",
        a2a_task_store=_env_text(source, "A2A_TASK_STORE", "memory") or "memory",
        a2a_host=_env_text(source, "A2A_HOST", "127.0.0.1") or "127.0.0.1",
        a2a_port=int(_env_text(source, "A2A_PORT", "41241") or "41241"),
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
