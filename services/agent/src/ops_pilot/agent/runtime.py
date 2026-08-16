"""Runtime assembly for the shared DeepAgent capability surface."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, cast

from deepagents import create_deep_agent
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver

from ops_pilot.agent.results import extract_result_text
from ops_pilot.mcp.registry import MCPRegistry, create_mcp_registry
from ops_pilot.models import create_chat_model
from ops_pilot.observability.langfuse import TracingSetup, create_callback_handler, flush_tracing
from ops_pilot.observability.metadata import build_model_metadata, build_runnable_config
from ops_pilot.reliability.run import RunController
from ops_pilot.runtime.spec import PersistenceSpec, RuntimeSpec
from ops_pilot.sandbox import SandboxManager, SandboxRuntime, create_sandbox_manager
from ops_pilot.skills.resolver import resolve_skill_paths
from ops_pilot.skills.sync import sync_skill_paths_to_backend


@dataclass(frozen=True)
class AgentRuntime:
    graph: Any
    spec: RuntimeSpec
    tools: tuple[Any, ...] = field(default_factory=tuple)
    skills: tuple[str, ...] = field(default_factory=tuple)
    mcp: MCPRegistry = field(default_factory=MCPRegistry)
    tracing: TracingSetup = field(default_factory=lambda: TracingSetup(enabled=False))
    sandbox: SandboxManager | SandboxRuntime | None = None
    model_metadata: dict[str, Any] = field(default_factory=dict)
    checkpointer_closer: Callable[[], Awaitable[None]] | None = None
    run_controller: RunController = field(default_factory=RunController)

    def close(self) -> None:
        if self.sandbox is not None:
            self.sandbox.close()

    async def aclose(self) -> None:
        try:
            try:
                if self.checkpointer_closer is not None:
                    await self.checkpointer_closer()
            finally:
                self.close()
        finally:
            flush_tracing(self.tracing)

    def runnable_config(
        self,
        *,
        protocol: str,
        thread_id: str | None = None,
        run_id: str | None = None,
        configurable: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> RunnableConfig:
        metadata = {**self.model_metadata, **(extra_metadata or {})}
        return build_runnable_config(
            self.spec,
            callbacks=self.tracing.callbacks,
            protocol=protocol,
            thread_id=thread_id,
            run_id=run_id,
            configurable=configurable,
            extra_metadata=metadata,
        )

    async def ainvoke_text(
        self,
        text: str,
        *,
        protocol: str,
        thread_id: str | None = None,
        run_id: str | None = None,
        configurable: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        context: Any | None = None,
    ) -> str:
        """Invoke the shared DeepAgent with one user text message."""

        effective_run_id = run_id or f"{protocol}:{thread_id or uuid.uuid4()}"

        async def invoke() -> Any:
            invoke_kwargs: dict[str, Any] = {
                "config": self.runnable_config(
                    protocol=protocol,
                    thread_id=thread_id,
                    run_id=effective_run_id,
                    configurable=configurable,
                    extra_metadata=extra_metadata,
                ),
                "version": "v2",
            }
            if context is not None:
                invoke_kwargs["context"] = context
            return await self.graph.ainvoke(
                {"messages": [{"role": "user", "content": text}]},
                **invoke_kwargs,
            )

        result = await self.run_controller.run(effective_run_id, invoke)
        return extract_result_text(_unwrap_graph_result(result))

    async def cancel_run(self, run_id: str, *, reason: str = "cancel requested") -> bool:
        return await self.run_controller.cancel(run_id, reason=reason)


async def build_agent_runtime(spec: RuntimeSpec) -> AgentRuntime:
    """Build one DeepAgent runtime from an explicit host composition.

    Runtime continuity is provided by the entrypoint's ``checkpointer``
    composition: in-memory, durable Postgres, or disabled. DeepAgents memory,
    skills, permissions, middleware, backend, interrupts, debug flag, and name
    are also passed through from the explicit runtime specification.
    """

    model = create_chat_model(spec.model)
    model_metadata = build_model_metadata(spec, model)
    mcp_registry = await create_mcp_registry(spec.mcp)
    # Human approval is a create_deep_agent(interrupt_on=...) declaration, not
    # an incidental property of an MCP transport definition.
    mcp_registry = replace(mcp_registry, hitl_tools=tuple(spec.interrupt_on))
    local_skills = tuple(str(path) for path in resolve_skill_paths(spec.skills))
    tracing = create_callback_handler(spec.observability)
    run_controller = RunController(
        default_deadline_seconds=spec.reliability.run_deadline_seconds if spec.reliability.enabled else None
    )

    sandbox: SandboxManager | None = None
    checkpointer_closer: Callable[[], Awaitable[None]] | None = None
    try:
        tools = [*mcp_registry.tools, *spec.tools]
        sandbox = create_sandbox_manager(spec.sandbox)
        middleware = _create_runtime_middleware(spec, mcp_registry.retry_tools, sandbox)
        checkpointer, checkpointer_closer = await _create_checkpointer(spec.persistence)
        skills = _resolve_backend_skill_paths(local_skills, sandbox)
        graph = _create_deep_agent(
            model=model,
            tools=tools,
            skills=list(skills),
            system_prompt=spec.system_prompt,
            checkpointer=checkpointer,
            backend=sandbox.backend if sandbox is not None else None,
            memory=list(spec.memory),
            permissions=[permission.as_deepagents_permission() for permission in spec.permissions],
            interrupt_on=spec.interrupt_on,
            middleware=[*middleware, *spec.middleware],
            context_schema=spec.context_schema,
            response_format=spec.response_format,
            debug=spec.debug,
            name=spec.name,
        )
    except Exception:
        if checkpointer_closer is not None:
            await checkpointer_closer()
        if sandbox is not None:
            sandbox.close()
        flush_tracing(tracing)
        raise
    return AgentRuntime(
        graph=graph,
        spec=spec,
        tools=tuple(tools),
        skills=skills,
        mcp=mcp_registry,
        tracing=tracing,
        sandbox=sandbox,
        model_metadata=model_metadata,
        checkpointer_closer=checkpointer_closer,
        run_controller=run_controller,
    )


def _resolve_backend_skill_paths(
    local_skills: tuple[str, ...],
    sandbox: SandboxManager | SandboxRuntime | None,
) -> tuple[str, ...]:
    if sandbox is None or not local_skills:
        return local_skills
    configure_skills = getattr(sandbox, "configure_skills", None)
    if configure_skills is not None:
        return configure_skills(local_skills)
    sync_result = sync_skill_paths_to_backend(local_skills, sandbox.backend)
    return sync_result.remote_paths


def _create_runtime_middleware(
    spec: RuntimeSpec,
    retry_tools: tuple[str, ...],
    sandbox: SandboxManager | SandboxRuntime | None,
) -> list[Any]:
    """Build the production guardrails from LangChain's official middleware."""

    middleware: list[Any] = []
    if spec.reliability.enabled:
        from langchain.agents.middleware import (
            ModelCallLimitMiddleware,
            ToolCallLimitMiddleware,
            ToolRetryMiddleware,
        )

        middleware.extend(
            (
                ModelCallLimitMiddleware(run_limit=spec.reliability.model_call_limit, exit_behavior="end"),
                ToolCallLimitMiddleware(run_limit=spec.reliability.tool_call_limit, exit_behavior="continue"),
            )
        )
        if retry_tools:
            middleware.append(
                ToolRetryMiddleware(
                    tools=list(retry_tools),
                    max_retries=spec.reliability.tool_retry_max_retries,
                    retry_on=(TimeoutError, ConnectionError),
                    initial_delay=spec.reliability.tool_retry_initial_delay_seconds,
                    backoff_factor=spec.reliability.tool_retry_backoff_factor,
                    max_delay=spec.reliability.tool_retry_max_delay_seconds,
                    jitter=spec.reliability.tool_retry_jitter,
                    on_failure="continue",
                )
            )
    if spec.todo_list_enabled:
        from langchain.agents.middleware import TodoListMiddleware

        middleware.append(TodoListMiddleware())
    if spec.filesystem_tools is not None:
        from deepagents.middleware import FilesystemMiddleware

        middleware.append(
            FilesystemMiddleware(
                backend=sandbox.backend if sandbox is not None else None,
                tools=cast(Any, list(spec.filesystem_tools)),
                _permissions=cast(Any, [permission.as_deepagents_permission() for permission in spec.permissions]),
            )
        )
    return middleware


def _create_deep_agent(
    *,
    model: Any,
    tools: list[Any],
    skills: list[str],
    system_prompt: str | None,
    checkpointer: Any | None,
    backend: Any | None,
    memory: list[str],
    permissions: list[dict[str, object]],
    interrupt_on: dict[str, Any] | None = None,
    middleware: Sequence[Any] = (),
    context_schema: type[Any] | None = None,
    response_format: Any | None = None,
    debug: bool = False,
    name: str | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools,
    }
    if system_prompt:
        kwargs["system_prompt"] = system_prompt
    if skills:
        kwargs["skills"] = skills
    if backend is not None:
        kwargs["backend"] = backend
    if memory:
        kwargs["memory"] = memory
    if permissions:
        kwargs["permissions"] = permissions
    if interrupt_on:
        kwargs["interrupt_on"] = interrupt_on

    kwargs["middleware"] = list(middleware)
    if context_schema is not None:
        kwargs["context_schema"] = context_schema
    if response_format is not None:
        kwargs["response_format"] = response_format

    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    if debug:
        kwargs["debug"] = True
    if name:
        kwargs["name"] = name

    return create_deep_agent(**kwargs)


async def _create_checkpointer(
    persistence: PersistenceSpec,
) -> tuple[Any | None, Callable[[], Awaitable[None]] | None]:
    """Build a LangGraph checkpointer for durable execution.

    Returns ``(checkpointer, closer)``. ``closer`` releases any owned resources
    (e.g. a Postgres connection pool) and must be awaited on runtime shutdown;
    it is ``None`` when the checkpointer holds nothing to release.
    """

    if persistence.backend == "none":
        return None, None
    if persistence.backend == "postgres":
        return await _create_postgres_checkpointer(persistence)
    return _create_memory_checkpointer(), None


def _create_memory_checkpointer() -> MemorySaver:
    return MemorySaver()


async def _create_postgres_checkpointer(
    persistence: PersistenceSpec,
) -> tuple[Any, Callable[[], Awaitable[None]]]:
    """Open a long-lived psycopg pool and wrap it in ``AsyncPostgresSaver``.

    The official production pattern owns the connection pool for the process
    lifetime (never per-request ``from_conn_string``) and runs ``setup()`` once
    to create the ``checkpoints``/``writes`` tables.
    """

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg import AsyncConnection
    from psycopg.rows import DictRow, dict_row
    from psycopg_pool import AsyncConnectionPool

    conn_string = _psycopg_database_url(persistence.database_url)
    if not conn_string:
        raise RuntimeError("persistence.backend is 'postgres' but DATABASE_URL is not set.")

    # autocommit + no prepared-statement server-side caching is what the
    # AsyncPostgresSaver examples use for pooled connections.
    pool: AsyncConnectionPool[AsyncConnection[DictRow]] = AsyncConnectionPool(
        conninfo=conn_string,
        max_size=20,
        open=False,
        connection_class=AsyncConnection[DictRow],
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True)
    try:
        checkpointer = AsyncPostgresSaver(pool)
        if persistence.setup_on_start:
            await checkpointer.setup()
    except Exception:
        await pool.close()
        raise

    async def _close() -> None:
        await pool.close()

    return checkpointer, _close


def _psycopg_database_url(database_url: str | None) -> str | None:
    if not database_url or not database_url.startswith("postgresql+"):
        return database_url
    rest = database_url[len("postgresql") :]
    return "postgresql" + rest[rest.index("://") :]


def _unwrap_graph_result(result: Any) -> Any:
    """Normalize LangGraph v2 output and never present an interrupt as a final answer."""

    if getattr(result, "interrupts", ()):
        raise RuntimeError("Agent execution paused for human approval.")
    return getattr(result, "value", result)
