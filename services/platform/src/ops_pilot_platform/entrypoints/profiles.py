"""Typed adapters from one entrypoint YAML composition to runtime specs."""

from __future__ import annotations

from typing import Any

from ops_pilot.mcp.spec import MCPServerCatalog, MCPServerSpec
from ops_pilot.runtime.spec import (
    FilesystemPermissionSpec,
    ModelSpec,
    ObservabilitySpec,
    PersistenceSpec,
    ReliabilitySpec,
    RuntimeSpec,
    SandboxSpec,
)

from ops_pilot_platform.entrypoints.environment import RuntimeEnvironment
from ops_pilot_platform.paths import resolve_repo_path


def runtime_spec_from_environment(
    environment: RuntimeEnvironment,
    *,
    id: str,
    entrypoint: str,
    default_assistant_id: str,
    tools: tuple[Any, ...] = (),
    middleware: tuple[Any, ...] = (),
    context_schema: type[Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RuntimeSpec:
    """Compose the host-neutral runtime once from a validated entrypoint view."""

    return RuntimeSpec(
        id=id,
        assistant_id=environment.deepagent.name or default_assistant_id,
        entrypoint=entrypoint,
        model=model_from_environment(environment),
        mcp=observer_mcp_from_environment(environment),
        **deepagent_fields_from_environment(environment),
        reliability=reliability_from_environment(environment),
        persistence=checkpointer_from_environment(environment),
        sandbox=sandbox_from_environment(environment),
        observability=observability_from_environment(environment),
        tools=tools,
        middleware=middleware,
        context_schema=context_schema,
        metadata=metadata or {},
    )


def model_from_environment(environment: RuntimeEnvironment) -> ModelSpec:
    model = environment.deepagent.model
    return ModelSpec(
        provider=model.provider,
        name=model.name,
        api_key=environment.model_api_key,
        base_url=model.base_url,
        temperature=model.temperature,
        max_tokens=model.max_tokens,
        request_timeout_seconds=model.timeout_seconds,
        reasoning_mode=model.reasoning.mode,
        reasoning_effort=model.reasoning.effort,
    )


def deepagent_fields_from_environment(environment: RuntimeEnvironment) -> dict[str, Any]:
    """Map YAML keys named after ``create_deep_agent`` arguments."""

    deepagent = environment.deepagent
    return {
        "system_prompt": deepagent.system_prompt,
        "skills": tuple(resolve_repo_path(path) for path in deepagent.skills),
        "memory": deepagent.memory,
        "permissions": tuple(
            FilesystemPermissionSpec(
                operations=permission.operations,
                paths=permission.paths,
                mode=permission.mode,
            )
            for permission in deepagent.permissions
        ),
        "filesystem_tools": deepagent.middleware.filesystem.tools,
        "todo_list_enabled": deepagent.middleware.todo_list,
        "interrupt_on": dict(deepagent.interrupt_on),
        "debug": deepagent.debug,
        "name": deepagent.name,
    }


def observability_from_environment(environment: RuntimeEnvironment) -> ObservabilitySpec:
    observability = environment.observability
    return ObservabilitySpec(
        enabled=observability.enabled,
        environment=observability.environment,
        public_key=environment.langfuse_public_key,
        secret_key=environment.langfuse_secret_key,
        base_url=observability.langfuse.base_url,
        timeout_seconds=observability.langfuse.timeout_seconds,
    )


def checkpointer_from_environment(environment: RuntimeEnvironment) -> PersistenceSpec:
    checkpointer = environment.deepagent.checkpointer
    return PersistenceSpec(
        backend=checkpointer.backend,
        database_url=environment.database_url,
        setup_on_start=checkpointer.setup_on_start,
    )


def sandbox_from_environment(environment: RuntimeEnvironment) -> SandboxSpec:
    backend = environment.deepagent.backend
    opensandbox = backend.opensandbox
    return SandboxSpec(
        enabled=backend.type == "opensandbox",
        domain=opensandbox.domain,
        api_key=environment.open_sandbox_api_key,
        protocol=opensandbox.protocol,
        use_server_proxy=opensandbox.use_server_proxy,
        image=opensandbox.image,
        timeout_seconds=opensandbox.timeout_seconds,
        ready_timeout_seconds=opensandbox.ready_timeout_seconds,
        scope=opensandbox.scope,
    )


def reliability_from_environment(environment: RuntimeEnvironment) -> ReliabilitySpec:
    reliability = environment.deepagent.middleware.reliability
    return ReliabilitySpec(
        enabled=reliability.enabled,
        run_deadline_seconds=reliability.run_deadline_seconds,
        model_call_limit=reliability.model_call_limit,
        tool_call_limit=reliability.tool_call_limit,
        recursion_limit=reliability.recursion_limit,
    )


def observer_mcp_from_environment(environment: RuntimeEnvironment) -> MCPServerCatalog:
    """Declare the MCP tools selected by the ``tools.mcp`` YAML subtree."""

    servers: list[MCPServerSpec] = []
    kubernetes = environment.deepagent.tools.mcp.kubernetes
    if kubernetes.kubeconfig:
        servers.append(
            MCPServerSpec(
                name="kubernetes",
                transport="stdio",
                command="npx",
                args=(
                    "-y",
                    "kubernetes-mcp-server@latest",
                    "--disable-multi-cluster",
                    "--kubeconfig",
                    kubernetes.kubeconfig,
                ),
                env={"KUBECONFIG": kubernetes.kubeconfig},
                read_timeout_seconds=kubernetes.read_timeout_seconds,
            )
        )

    basic_auth = environment.mcp_basic_auth_header
    headers = {"Authorization": basic_auth} if basic_auth else {}
    for name, configuration in (
        ("jaeger", environment.deepagent.tools.mcp.jaeger),
        ("prometheus", environment.deepagent.tools.mcp.prometheus),
    ):
        if configuration.url:
            servers.append(
                MCPServerSpec(
                    name=name,
                    transport="streamable_http",
                    url=configuration.url,
                    headers=headers,
                    timeout=configuration.timeout_seconds,
                    read_timeout_seconds=configuration.read_timeout_seconds,
                    retry_tools=configuration.retry_tools,
                )
            )

    return MCPServerCatalog(tuple(servers))
