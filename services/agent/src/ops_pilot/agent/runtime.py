"""Runtime assembly for the shared DeepAgent capability surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ops_pilot.agent.middleware import NormalizeSystemMessagesMiddleware
from ops_pilot.agent.state import OpsPilotState
from ops_pilot.config.settings import Settings, load_settings
from ops_pilot.mcp.registry import MCPRegistry, create_mcp_registry
from ops_pilot.models.sap_genai import create_chat_model
from ops_pilot.observability.langfuse import TracingSetup, create_callback_handler
from ops_pilot.observability.metadata import build_runnable_config
from ops_pilot.skills.resolver import resolve_skill_paths
from ops_pilot.tools.dynatrace_dashboard import get_dynatrace_dashboard_tools
from ops_pilot.tools.smoke_tools import get_smoke_tools


@dataclass(frozen=True)
class AgentRuntime:
    graph: Any
    settings: Settings
    tools: tuple[Any, ...] = field(default_factory=tuple)
    skills: tuple[str, ...] = field(default_factory=tuple)
    mcp: MCPRegistry = field(default_factory=MCPRegistry)
    tracing: TracingSetup = field(default_factory=lambda: TracingSetup(enabled=False))

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
        return build_runnable_config(
            self.settings,
            callbacks=self.tracing.callbacks,
            protocol=protocol,
            thread_id=thread_id,
            run_id=run_id,
            a2a_task_id=a2a_task_id,
            a2a_context_id=a2a_context_id,
            configurable=configurable,
            extra_metadata=extra_metadata,
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

        result = await self.graph.ainvoke(
            {"messages": [{"role": "user", "content": text}]},
            config=self.runnable_config(
                protocol=protocol,
                thread_id=thread_id,
                run_id=run_id,
                a2a_task_id=a2a_task_id,
                a2a_context_id=a2a_context_id,
                configurable=configurable,
                extra_metadata=extra_metadata,
            ),
        )
        return _extract_result_text(result)


async def build_agent_runtime(
    settings: Settings | None = None,
    *,
    use_memory_checkpointer: bool = True,
) -> AgentRuntime:
    """Build the shared DeepAgent runtime.

    DeepAgents long-term/semantic memory is intentionally not configured here.
    Runtime continuity is provided by LangGraph's checkpointer when available.
    """

    resolved_settings = settings or load_settings()
    model = create_chat_model(resolved_settings)
    mcp_registry = await create_mcp_registry(resolved_settings)
    skills = tuple(resolve_skill_paths(resolved_settings))
    tracing = create_callback_handler(resolved_settings)

    tools = list(mcp_registry.tools)
    if resolved_settings.enable_smoke_tools:
        tools.extend(get_smoke_tools())
    if resolved_settings.enable_dynatrace_dashboard:
        tools.extend(get_dynatrace_dashboard_tools())

    graph = _create_deep_agent(
        model=model,
        tools=tools,
        skills=list(skills),
        system_prompt=resolved_settings.configured_system_prompt(),
        tracing=tracing,
        use_memory_checkpointer=use_memory_checkpointer,
    )
    return AgentRuntime(
        graph=graph,
        settings=resolved_settings,
        tools=tuple(tools),
        skills=skills,
        mcp=mcp_registry,
        tracing=tracing,
    )


def _create_deep_agent(
    *,
    model: Any,
    tools: list[Any],
    skills: list[str],
    system_prompt: str | None,
    tracing: TracingSetup,
    use_memory_checkpointer: bool,
) -> Any:
    try:
        from deepagents import create_deep_agent
    except ImportError as exc:
        raise RuntimeError("deepagents is not installed. Run 'uv sync' in services/agent.") from exc

    kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools,
        "state_schema": OpsPilotState,
    }
    if system_prompt:
        kwargs["system_prompt"] = system_prompt
    if skills:
        kwargs["skills"] = skills

    copilotkit_middleware = _create_copilotkit_middleware()
    middleware = [NormalizeSystemMessagesMiddleware()]
    if copilotkit_middleware is not None:
        middleware.insert(0, copilotkit_middleware)
    kwargs["middleware"] = middleware

    if use_memory_checkpointer:
        checkpointer = _create_memory_checkpointer()
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


def _create_memory_checkpointer() -> Any | None:
    try:
        from langgraph.checkpoint.memory import MemorySaver
    except ImportError:
        return None
    return MemorySaver()


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
