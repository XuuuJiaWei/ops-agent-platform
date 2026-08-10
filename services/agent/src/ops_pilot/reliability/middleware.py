"""LangChain tool-call adapter for reliable MCP execution."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping, Set
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from ops_pilot.mcp.errors import is_mcp_session_disconnect
from ops_pilot.reliability.execution import (
    CircuitOpenError,
    IndeterminateToolError,
    RecoverableToolError,
    ReliableToolExecutor,
    ToolCall,
    TransientToolError,
)
from ops_pilot.reliability.run import current_run_id

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
TRANSIENT_TEXT = re.compile(
    r"(?:\b(?:429|500|502|503|504)\b|too many requests|rate.?limit|service unavailable|bad gateway|gateway timeout)",
    re.IGNORECASE,
)


class ReliableToolMiddleware(AgentMiddleware):
    """Apply idempotency, classified retries, and server-local circuit breaking to MCP tools."""

    def __init__(
        self,
        *,
        executor: ReliableToolExecutor,
        tool_servers: Mapping[str, str],
        retry_tools: Set[str] | None = None,
    ) -> None:
        self._executor = executor
        self._tool_servers = dict(tool_servers)
        self._retry_tools = frozenset(retry_tools or ())

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tool_name = str(request.tool_call.get("name", ""))
        dependency = self._tool_servers.get(tool_name)
        if dependency is None:
            return await handler(request)

        tool_call_id = str(request.tool_call.get("id", ""))
        run_id = _request_run_id(request) or f"unscoped:{tool_call_id}"
        call = ToolCall(
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=request.tool_call.get("args") or {},
            dependency=dependency,
            retry_safe=_retry_safe(request, explicitly_safe=tool_name in self._retry_tools),
        )

        async def operation() -> ToolMessage | Command[Any]:
            try:
                result = await handler(request)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                classified = _classify_exception(exc)
                if classified is not None:
                    raise classified from exc
                raise
            if isinstance(result, ToolMessage) and result.status == "error":
                if _is_transient_text(result.content):
                    raise TransientToolError(str(result.content), tool_result=result)
                raise RecoverableToolError(str(result.content), tool_result=result)
            return result

        try:
            outcome = await self._executor.execute(call, operation)
        except CircuitOpenError as exc:
            return _error_message(tool_call_id, f"MCP server unavailable: {exc} Try another tool or wait for recovery.")
        except IndeterminateToolError as exc:
            return _error_message(
                tool_call_id,
                f"Tool outcome is unknown: {exc} Do not repeat this write blindly; reconcile its external state first.",
            )
        except TransientToolError as exc:
            if isinstance(exc.tool_result, ToolMessage):
                return exc.tool_result
            return _error_message(tool_call_id, f"Transient MCP failure after bounded retries: {exc}")
        return outcome.value


def _request_run_id(request: ToolCallRequest) -> str | None:
    config = getattr(request.runtime, "config", None) or {}
    metadata = config.get("metadata") or {}
    configurable = config.get("configurable") or {}
    value = (
        metadata.get("run_id")
        or configurable.get("run_id")
        or current_run_id()
        or metadata.get("a2a_task_id")
        or configurable.get("a2a_task_id")
        or metadata.get("thread_id")
        or configurable.get("thread_id")
    )
    return str(value) if value else None


def _retry_safe(request: ToolCallRequest, *, explicitly_safe: bool) -> bool:
    metadata = getattr(request.tool, "metadata", None) or {}
    return explicitly_safe or metadata.get("readOnlyHint") is True or metadata.get("idempotentHint") is True


def _classify_exception(exc: BaseException) -> TransientToolError | None:
    if is_mcp_session_disconnect(exc):
        return IndeterminateToolError(str(exc) or exc.__class__.__name__)
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    if status_code in TRANSIENT_STATUS_CODES:
        return TransientToolError(str(exc) or exc.__class__.__name__, status_code=status_code)
    if isinstance(exc, TimeoutError | ConnectionError | OSError):
        return IndeterminateToolError(str(exc) or exc.__class__.__name__)
    return None


def _is_transient_text(content: Any) -> bool:
    return bool(TRANSIENT_TEXT.search(str(content)))


def _error_message(tool_call_id: str, content: str) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tool_call_id, status="error")
