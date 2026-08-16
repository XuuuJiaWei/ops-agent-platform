"""Small, reusable building blocks for explicit runtime profiles.

The helpers only resolve values named by the calling entrypoint.  They never
read a profile file and never choose capabilities on the host's behalf.
"""

from __future__ import annotations

from pathlib import Path

from ops_pilot.entrypoints.environment import RuntimeEnvironment
from ops_pilot.mcp.spec import MCPServerCatalog, MCPServerSpec
from ops_pilot.runtime.spec import (
    ModelSpec,
    ObservabilitySpec,
    PersistenceSpec,
    ReliabilitySpec,
    SandboxSpec,
)


def model_from_environment(environment: RuntimeEnvironment) -> ModelSpec:
    return ModelSpec(
        provider=environment.model_provider,
        name=environment.model_name,
        api_key=environment.model_api_key,
        base_url=environment.model_base_url,
        temperature=environment.model_temperature,
        max_tokens=environment.model_max_tokens,
        request_timeout_seconds=environment.model_timeout_seconds,
        reasoning_mode=environment.model_reasoning_mode,
        reasoning_effort=environment.model_reasoning_effort,
    )


def observability_from_environment(environment: RuntimeEnvironment) -> ObservabilitySpec:
    return ObservabilitySpec(
        environment=environment.environment,
        public_key=environment.langfuse_public_key,
        secret_key=environment.langfuse_secret_key,
        base_url=environment.langfuse_base_url,
        timeout_seconds=environment.langfuse_timeout_seconds,
    )


def persistence_from_environment(environment: RuntimeEnvironment) -> PersistenceSpec:
    return PersistenceSpec(
        backend=environment.persistence_backend,
        database_url=environment.database_url,
        setup_on_start=environment.persistence_setup_on_start,
    )


def sandbox_from_environment(environment: RuntimeEnvironment) -> SandboxSpec:
    return SandboxSpec(
        enabled=environment.open_sandbox_enabled,
        domain=environment.open_sandbox_domain,
        api_key=environment.open_sandbox_api_key,
        protocol=environment.open_sandbox_protocol,
        use_server_proxy=environment.open_sandbox_use_server_proxy,
        image=environment.open_sandbox_image,
        timeout_seconds=environment.open_sandbox_timeout_seconds,
        ready_timeout_seconds=environment.open_sandbox_ready_timeout_seconds,
        scope=environment.open_sandbox_scope,
    )


def reliability_from_environment(environment: RuntimeEnvironment) -> ReliabilitySpec:
    return ReliabilitySpec(
        enabled=environment.reliability_enabled,
        run_deadline_seconds=environment.run_deadline_seconds,
        model_call_limit=environment.model_call_limit,
        tool_call_limit=environment.tool_call_limit,
    )


def observer_mcp_from_environment(environment: RuntimeEnvironment) -> MCPServerCatalog:
    """Declare the read-only observability MCP surface requested by this host."""

    servers: list[MCPServerSpec] = []
    kubeconfig = environment.kubeconfig
    if kubeconfig:
        servers.append(
            MCPServerSpec(
                name="kubernetes",
                transport="stdio",
                command="npx",
                args=("-y", "kubernetes-mcp-server@latest", "--disable-multi-cluster", "--kubeconfig", kubeconfig),
                env={"KUBECONFIG": kubeconfig},
                read_timeout_seconds=60,
                hitl_tools=(
                    "pods_delete",
                    "pods_exec",
                    "pods_run",
                    "resources_create_or_update",
                    "resources_delete",
                    "resources_scale",
                ),
            )
        )

    basic_auth = environment.mcp_basic_auth_header
    headers = {"Authorization": basic_auth} if basic_auth else {}
    for name, url, retry_tools in (
        ("jaeger", environment.jaeger_mcp_url, ("search_traces", "get_services", "get_span_details")),
        ("prometheus", environment.prometheus_mcp_url, ()),
    ):
        if url:
            servers.append(
                MCPServerSpec(
                    name=name,
                    transport="streamable_http",
                    url=url,
                    headers=headers,
                    timeout=90,
                    read_timeout_seconds=30,
                    retry_tools=retry_tools,
                )
            )

    return MCPServerCatalog(tuple(servers))


def project_skills() -> tuple[Path, ...]:
    return (Path("skills"),)
