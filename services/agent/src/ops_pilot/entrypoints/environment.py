"""Validated, entrypoint-scoped deployment settings."""

from __future__ import annotations

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ops_pilot.config.paths import REPO_ROOT
from ops_pilot.runtime.spec import ModelProvider, PersistenceBackend, ReasoningEffort, ReasoningMode, SandboxScope


class RuntimeEnvironment(BaseSettings):
    """One entrypoint's typed deployment values, never a capability catalog.

    ``for_entrypoint`` assigns an environment prefix such as
    ``OPS_PILOT_WEB_``.  Runtime capabilities remain declared by the matching
    Python entrypoint; this model only validates values that deployment passes
    to that entrypoint.
    """

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    model_provider: ModelProvider = "sap"
    model_name: str = "anthropic--claude-4.6-sonnet"
    model_api_key: str | None = Field(default=None, validation_alias=AliasChoices("MODEL_API_KEY"))
    model_base_url: str | None = None
    model_temperature: float = 0.0
    model_max_tokens: int = 16384
    model_timeout_seconds: int = 120
    model_reasoning_mode: ReasoningMode = "adaptive"
    model_reasoning_effort: ReasoningEffort = "medium"
    assistant_id: str | None = None
    system_prompt: str | None = None

    environment: str = "local"
    langfuse_public_key: str | None = Field(default=None, validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY"))
    langfuse_secret_key: str | None = Field(default=None, validation_alias=AliasChoices("LANGFUSE_SECRET_KEY"))
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_timeout_seconds: int = 30

    persistence_backend: PersistenceBackend = "memory"
    database_url: str | None = Field(default=None, validation_alias=AliasChoices("DATABASE_URL"))
    persistence_setup_on_start: bool = True

    open_sandbox_enabled: bool = False
    open_sandbox_domain: str | None = None
    open_sandbox_api_key: str | None = Field(default=None, validation_alias=AliasChoices("OPEN_SANDBOX_API_KEY"))
    open_sandbox_protocol: str = "https"
    open_sandbox_use_server_proxy: bool = True
    open_sandbox_image: str = "python:3.11"
    open_sandbox_timeout_seconds: int = 600
    open_sandbox_ready_timeout_seconds: int = 240
    open_sandbox_scope: SandboxScope = "thread"

    reliability_enabled: bool = True
    run_deadline_seconds: float = 600
    model_call_limit: int = 50
    tool_call_limit: int = 200

    kubeconfig: str | None = None
    jaeger_mcp_url: str | None = None
    prometheus_mcp_url: str | None = None
    mcp_basic_auth_header: str | None = None

    host: str = "127.0.0.1"
    port: int = 8123
    chat_base_path: str = "/chat"
    a2a_base_path: str = "/a2a"
    enable_spaces: bool = True
    enable_a2a: bool = True

    @classmethod
    def for_entrypoint(cls, name: str) -> RuntimeEnvironment:
        """Read the process environment for exactly one named host."""

        # Pydantic Settings reads this file for this model. Loading it into the
        # process as well is intentional: SAP's official SDK reads its own
        # AICORE_* variables directly from the process environment.
        load_dotenv(REPO_ROOT / ".env", override=False)
        return cls(_env_prefix=f"OPS_PILOT_{name.upper()}_")  # type: ignore[reportCallIssue]
