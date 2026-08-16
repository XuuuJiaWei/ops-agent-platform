"""Typed adapters from one entrypoint YAML composition to runtime specs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ops_pilot.entrypoints.environment import RuntimeEnvironment
from ops_pilot.mcp.spec import MCPServerCatalog, MCPServerSpec
from ops_pilot.runtime.spec import (
    FilesystemPermissionSpec,
    ModelSpec,
    ObservabilitySpec,
    PersistenceSpec,
    ReliabilitySpec,
    SandboxSpec,
)


def model_from_environment(environment: RuntimeEnvironment) -> ModelSpec:
    model = environment.model
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

    return {
        "system_prompt": environment.system_prompt,
        "skills": tuple(Path(path) for path in environment.skills),
        "memory": environment.memory,
        "permissions": tuple(
            FilesystemPermissionSpec(
                operations=permission.operations,
                paths=permission.paths,
                mode=permission.mode,
            )
            for permission in environment.permissions
        ),
        "filesystem_tools": environment.middleware.filesystem.tools,
        "todo_list_enabled": environment.middleware.todo_list,
        "interrupt_on": dict(environment.interrupt_on),
        "debug": environment.debug,
        "name": environment.name,
    }


def observability_from_environment(environment: RuntimeEnvironment) -> ObservabilitySpec:
    observability = environment.observability
    return ObservabilitySpec(
        environment=observability.environment,
        public_key=environment.langfuse_public_key,
        secret_key=environment.langfuse_secret_key,
        base_url=observability.langfuse.base_url,
        timeout_seconds=observability.langfuse.timeout_seconds,
    )


def checkpointer_from_environment(environment: RuntimeEnvironment) -> PersistenceSpec:
    checkpointer = environment.checkpointer
    return PersistenceSpec(
        backend=checkpointer.backend,
        database_url=environment.database_url,
        setup_on_start=checkpointer.setup_on_start,
    )


def sandbox_from_environment(environment: RuntimeEnvironment) -> SandboxSpec:
    backend = environment.backend
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
    reliability = environment.middleware.reliability
    return ReliabilitySpec(
        enabled=reliability.enabled,
        run_deadline_seconds=reliability.run_deadline_seconds,
        model_call_limit=reliability.model_call_limit,
        tool_call_limit=reliability.tool_call_limit,
    )


def observer_mcp_from_environment(environment: RuntimeEnvironment) -> MCPServerCatalog:
    """Declare the MCP tools selected by the ``tools.mcp`` YAML subtree."""

    servers: list[MCPServerSpec] = []
    kubernetes = environment.tools.mcp.kubernetes
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
        ("jaeger", environment.tools.mcp.jaeger),
        ("prometheus", environment.tools.mcp.prometheus),
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
