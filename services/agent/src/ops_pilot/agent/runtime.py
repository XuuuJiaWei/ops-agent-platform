"""Runtime assembly for the shared DeepAgent capability surface."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ops_pilot.agent.middleware import NormalizeSystemMessagesMiddleware
from ops_pilot.config.settings import Settings, load_settings
from ops_pilot.mcp.registry import MCPRegistry, create_mcp_registry
from ops_pilot.models import create_chat_model
from ops_pilot.observability.langfuse import TracingSetup, create_callback_handler
from ops_pilot.observability.metadata import build_model_metadata, build_runnable_config
from ops_pilot.reliability.execution import (
    CircuitBreakerPolicy,
    ReliableToolExecutor,
    RetryPolicy,
)
from ops_pilot.reliability.journal import create_execution_journal
from ops_pilot.reliability.middleware import ReliableToolMiddleware
from ops_pilot.reliability.run import RunController
from ops_pilot.sandbox import SandboxManager, SandboxRuntime, create_sandbox_manager
from ops_pilot.skills.resolver import resolve_skill_paths
from ops_pilot.skills.sync import sync_skill_paths_to_backend
from ops_pilot.spaces import MemorySpaceRepository, SpaceRepository, build_space_tools, create_space_repository
from ops_pilot.tools.smoke_tools import get_smoke_tools

if TYPE_CHECKING:
    from ops_pilot.eval.trace import AgentTrace


@dataclass(frozen=True)
class AgentRuntime:
    graph: Any
    settings: Settings
    tools: tuple[Any, ...] = field(default_factory=tuple)
    skills: tuple[str, ...] = field(default_factory=tuple)
    mcp: MCPRegistry = field(default_factory=MCPRegistry)
    tracing: TracingSetup = field(default_factory=lambda: TracingSetup(enabled=False))
    sandbox: SandboxManager | SandboxRuntime | None = None
    model_metadata: dict[str, Any] = field(default_factory=dict)
    checkpointer_closer: Callable[[], Awaitable[None]] | None = None
    spaces: SpaceRepository = field(default_factory=MemorySpaceRepository)
    space_repository_closer: Callable[[], Awaitable[None]] | None = None
    run_controller: RunController = field(default_factory=RunController)
    execution_journal_closer: Callable[[], Awaitable[None]] | None = None

    def close(self) -> None:
        if self.sandbox is not None:
            self.sandbox.close()

    async def aclose(self) -> None:
        try:
            await self.mcp.aclose()
        finally:
            try:
                if self.checkpointer_closer is not None:
                    await self.checkpointer_closer()
            finally:
                try:
                    if self.space_repository_closer is not None:
                        await self.space_repository_closer()
                finally:
                    try:
                        if self.execution_journal_closer is not None:
                            await self.execution_journal_closer()
                    finally:
                        self.close()

    def runnable_config(
        self,
        *,
        protocol: str,
        thread_id: str | None = None,
        run_id: str | None = None,
        a2a_task_id: str | None = None,
        a2a_context_id: str | None = None,
        configurable: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = {**self.model_metadata, **(extra_metadata or {})}
        return build_runnable_config(
            self.settings,
            callbacks=self.tracing.callbacks,
            protocol=protocol,
            recursion_limit=_graph_recursion_limit(self.graph),
            thread_id=thread_id,
            run_id=run_id,
            a2a_task_id=a2a_task_id,
            a2a_context_id=a2a_context_id,
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
        a2a_task_id: str | None = None,
        a2a_context_id: str | None = None,
        configurable: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Invoke the shared DeepAgent with one user text message."""

        effective_run_id = run_id or a2a_task_id or f"{protocol}:{thread_id or uuid.uuid4()}"

        async def invoke() -> Any:
            return await self.graph.ainvoke(
                {"messages": [{"role": "user", "content": text}]},
                config=self.runnable_config(
                    protocol=protocol,
                    thread_id=thread_id,
                    run_id=effective_run_id,
                    a2a_task_id=a2a_task_id,
                    a2a_context_id=a2a_context_id,
                    configurable=configurable,
                    extra_metadata=extra_metadata,
                ),
            )

        result = await self.run_controller.run(effective_run_id, invoke)
        return _extract_result_text(result)

    async def ainvoke_trace(
        self,
        text: str,
        *,
        protocol: str,
        thread_id: str | None = None,
        run_id: str | None = None,
        a2a_task_id: str | None = None,
        a2a_context_id: str | None = None,
        configurable: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        deadline_seconds: float | None = None,
    ) -> AgentTrace:
        """Invoke the shared DeepAgent and return structured eval trace signals."""

        from ops_pilot.eval.trace import build_agent_trace

        started = time.perf_counter()
        effective_run_id = run_id or a2a_task_id or f"{protocol}:{thread_id or uuid.uuid4()}"

        async def invoke() -> Any:
            return await self.graph.ainvoke(
                {"messages": [{"role": "user", "content": text}]},
                config=self.runnable_config(
                    protocol=protocol,
                    thread_id=thread_id,
                    run_id=effective_run_id,
                    a2a_task_id=a2a_task_id,
                    a2a_context_id=a2a_context_id,
                    configurable=configurable,
                    extra_metadata=extra_metadata,
                ),
            )

        try:
            result = await self.run_controller.run(
                effective_run_id,
                invoke,
                deadline_seconds=deadline_seconds,
            )
        except TimeoutError as exc:
            effective_deadline = self.settings.run_deadline_seconds if deadline_seconds is None else deadline_seconds
            if effective_deadline is None:
                raise
            raise TimeoutError(f"Agent invocation timed out after {effective_deadline:g}s.") from exc
        return build_agent_trace(result, latency_s=time.perf_counter() - started)

    async def cancel_run(self, run_id: str, *, reason: str = "cancel requested") -> bool:
        return await self.run_controller.cancel(run_id, reason=reason)


async def build_agent_runtime(
    settings: Settings | None = None,
    *,
    attach_checkpointer: bool = True,
) -> AgentRuntime:
    """Build the shared DeepAgent runtime.

    DeepAgents long-term/semantic memory is intentionally not configured here.
    Runtime continuity is provided by LangGraph's checkpointer: an in-memory
    saver by default, or a durable ``AsyncPostgresSaver`` when
    ``persistence.backend`` is ``postgres``. ``attach_checkpointer=False`` skips
    it for callers that supply their own persistence (e.g. the LangGraph
    platform server) or need a stateless graph (eval runs).
    """

    resolved_settings = settings or load_settings()
    model = create_chat_model(resolved_settings)
    model_metadata = build_model_metadata(resolved_settings, model)
    mcp_registry = await create_mcp_registry(resolved_settings)
    local_skills = tuple(resolve_skill_paths(resolved_settings))
    tracing = create_callback_handler(resolved_settings)
    run_controller = RunController(default_deadline_seconds=resolved_settings.run_deadline_seconds)

    sandbox: SandboxManager | None = None
    checkpointer_closer: Callable[[], Awaitable[None]] | None = None
    space_repository: SpaceRepository | None = None
    space_repository_closer: Callable[[], Awaitable[None]] | None = None
    execution_journal_closer: Callable[[], Awaitable[None]] | None = None
    try:
        journal, execution_journal_closer = await create_execution_journal(resolved_settings)
        tool_executor = ReliableToolExecutor(
            journal=journal,
            retry_policy=RetryPolicy(
                max_attempts=resolved_settings.tool_retry_max_attempts,
                initial_backoff_seconds=resolved_settings.tool_retry_initial_backoff_seconds,
                backoff_multiplier=resolved_settings.tool_retry_backoff_multiplier,
                jitter_ratio=resolved_settings.tool_retry_jitter_ratio,
            ),
            circuit_breaker_policy=CircuitBreakerPolicy(
                failure_threshold=resolved_settings.circuit_breaker_failure_threshold,
                recovery_timeout_seconds=resolved_settings.circuit_breaker_recovery_seconds,
            ),
        )
        reliability_middleware = (
            ReliableToolMiddleware(
                executor=tool_executor,
                tool_servers=mcp_registry.tool_servers,
                retry_tools=set(mcp_registry.retry_tools),
            )
            if resolved_settings.reliability_enabled
            else None
        )
        space_repository, space_repository_closer = await create_space_repository(resolved_settings)
        tools = [*mcp_registry.tools, *build_space_tools(space_repository)]
        if resolved_settings.enable_smoke_tools:
            tools.extend(get_smoke_tools())
        checkpointer, checkpointer_closer = (
            await _create_checkpointer(resolved_settings) if attach_checkpointer else (None, None)
        )
        sandbox = create_sandbox_manager(resolved_settings)
        skills = _resolve_backend_skill_paths(local_skills, sandbox)
        interrupt_on = {name: True for name in mcp_registry.hitl_tools}
        graph = _create_deep_agent(
            model=model,
            tools=tools,
            skills=list(skills),
            system_prompt=_system_prompt(resolved_settings.configured_system_prompt()),
            tracing=tracing,
            checkpointer=checkpointer,
            backend=sandbox.backend if sandbox is not None else None,
            interrupt_on=interrupt_on,
            reliability_middleware=reliability_middleware,
        )
    except Exception:
        await mcp_registry.aclose()
        if checkpointer_closer is not None:
            await checkpointer_closer()
        if space_repository_closer is not None:
            await space_repository_closer()
        if execution_journal_closer is not None:
            await execution_journal_closer()
        if sandbox is not None:
            sandbox.close()
        raise
    assert space_repository is not None
    return AgentRuntime(
        graph=graph,
        settings=resolved_settings,
        tools=tuple(tools),
        skills=skills,
        mcp=mcp_registry,
        tracing=tracing,
        sandbox=sandbox,
        model_metadata=model_metadata,
        checkpointer_closer=checkpointer_closer,
        spaces=space_repository,
        space_repository_closer=space_repository_closer,
        run_controller=run_controller,
        execution_journal_closer=execution_journal_closer,
    )


def _system_prompt(configured_prompt: str | None) -> str:
    spaces_prompt = """You can create agent-native visual experiences with Space tools.
Use render_ui for a transient card that belongs in the current conversation.
Use create_space and the card-in-space tools when the user wants a persistent dashboard.
Before changing an existing Space, use list_spaces or get_space when you do not already have its current ids.
Cards are declarative data: choose the card type that best communicates the result and keep labels concise."""
    if configured_prompt:
        return f"{configured_prompt}\n\n{spaces_prompt}"
    return spaces_prompt


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


def _create_deep_agent(
    *,
    model: Any,
    tools: list[Any],
    skills: list[str],
    system_prompt: str | None,
    tracing: TracingSetup,
    checkpointer: Any | None,
    backend: Any | None,
    interrupt_on: dict[str, Any] | None = None,
    reliability_middleware: Any | None = None,
) -> Any:
    try:
        from deepagents import create_deep_agent
    except ImportError as exc:
        raise RuntimeError("deepagents is not installed. Run 'uv sync' in services/agent.") from exc

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
    if interrupt_on:
        kwargs["interrupt_on"] = interrupt_on

    copilotkit_middleware = _create_copilotkit_middleware()
    middleware = [NormalizeSystemMessagesMiddleware()]
    if reliability_middleware is not None:
        middleware.insert(0, reliability_middleware)
    if copilotkit_middleware is not None:
        middleware.insert(0, copilotkit_middleware)
    kwargs["middleware"] = middleware

    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer

    graph = create_deep_agent(**kwargs)
    if tracing.callbacks:
        graph = graph.with_config({"callbacks": list(tracing.callbacks)})
    return graph


def _create_copilotkit_middleware() -> Any | None:
    try:
        from copilotkit import CopilotKitMiddleware
    except ImportError:
        return None
    return CopilotKitMiddleware()


async def _create_checkpointer(
    settings: Settings,
) -> tuple[Any | None, Callable[[], Awaitable[None]] | None]:
    """Build a LangGraph checkpointer for durable execution.

    Returns ``(checkpointer, closer)``. ``closer`` releases any owned resources
    (e.g. a Postgres connection pool) and must be awaited on runtime shutdown;
    it is ``None`` when the checkpointer holds nothing to release.
    """

    if settings.persistence_backend == "postgres":
        return await _create_postgres_checkpointer(settings)
    return _create_memory_checkpointer(), None


def _create_memory_checkpointer() -> Any | None:
    try:
        from langgraph.checkpoint.memory import MemorySaver
    except ImportError:
        return None
    return MemorySaver()


async def _create_postgres_checkpointer(
    settings: Settings,
) -> tuple[Any, Callable[[], Awaitable[None]]]:
    """Open a long-lived psycopg pool and wrap it in ``AsyncPostgresSaver``.

    The official production pattern owns the connection pool for the process
    lifetime (never per-request ``from_conn_string``) and runs ``setup()`` once
    to create the ``checkpoints``/``writes`` tables.
    """

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    conn_string = settings.psycopg_database_url()
    if not conn_string:
        raise RuntimeError("persistence.backend is 'postgres' but DATABASE_URL is not set.")

    # autocommit + no prepared-statement server-side caching is what the
    # AsyncPostgresSaver examples use for pooled connections.
    pool = AsyncConnectionPool(
        conninfo=conn_string,
        max_size=20,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open(wait=True)
    try:
        checkpointer = AsyncPostgresSaver(pool)
        if settings.persistence_setup_on_start:
            await checkpointer.setup()
    except Exception:
        await pool.close()
        raise

    async def _close() -> None:
        await pool.close()

    return checkpointer, _close


def _graph_recursion_limit(graph: Any) -> int | None:
    config = getattr(graph, "config", None)
    if isinstance(config, dict):
        value = config.get("recursion_limit")
        if isinstance(value, int):
            return value
    return None


def _extract_result_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            return _message_content(messages[-1])
        for key in ("output", "content"):
            value = result.get(key)
            if value is not None:
                return str(value)
    return _message_content(result)


def _message_content(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is not None:
        return _stringify_content(content)
    if isinstance(message, dict) and "content" in message:
        return _stringify_content(message["content"])
    return str(message)


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text is not None:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)
