from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from langchain.tools import ToolRuntime
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, ErrorData

from ops_pilot.reliability.execution import MemoryExecutionJournal, ReliableToolExecutor, RetryPolicy
from ops_pilot.reliability.middleware import ReliableToolMiddleware


def _tool(name: str, metadata: dict[str, bool]) -> BaseTool:
    return cast(BaseTool, SimpleNamespace(name=name, metadata=metadata))


@pytest.mark.asyncio
async def test_mcp_503_tool_result_is_retried_without_asking_model_again() -> None:
    middleware = ReliableToolMiddleware(
        executor=ReliableToolExecutor(
            journal=MemoryExecutionJournal(),
            retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0),
        ),
        tool_servers={"query_metrics": "prometheus"},
    )
    request = ToolCallRequest(
        tool_call={"id": "call-503", "name": "query_metrics", "args": {"query": "up"}},
        tool=_tool("query_metrics", {"readOnlyHint": True}),
        state={},
        runtime=ToolRuntime(
            state={},
            context=None,
            config={"metadata": {"run_id": "run-503"}},
            stream_writer=lambda _: None,
            tool_call_id="call-503",
            store=None,
            tools=[],
        ),
    )
    attempts = 0

    async def handler(_: ToolCallRequest) -> ToolMessage:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return ToolMessage(content="HTTP 503 Service Unavailable", tool_call_id="call-503", status="error")
        return ToolMessage(content="up == 1", tool_call_id="call-503")

    result = await middleware.awrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert result.content == "up == 1"
    assert result.status == "success"
    assert attempts == 2


@pytest.mark.asyncio
async def test_business_error_is_returned_to_agent_and_duplicate_reuses_it() -> None:
    middleware = ReliableToolMiddleware(
        executor=ReliableToolExecutor(journal=MemoryExecutionJournal()),
        tool_servers={"restart": "kubernetes"},
    )
    request = ToolCallRequest(
        tool_call={"id": "call-invalid", "name": "restart", "args": {"deployment": "missing"}},
        tool=_tool("restart", {"destructiveHint": True}),
        state={},
        runtime=ToolRuntime(
            state={},
            context=None,
            config={"metadata": {"run_id": "run-invalid"}},
            stream_writer=lambda _: None,
            tool_call_id="call-invalid",
            store=None,
            tools=[],
        ),
    )
    attempts = 0

    async def handler(_: ToolCallRequest) -> ToolMessage:
        nonlocal attempts
        attempts += 1
        return ToolMessage(content="deployment does not exist", tool_call_id="call-invalid", status="error")

    first = await middleware.awrap_tool_call(request, handler)
    duplicate = await middleware.awrap_tool_call(request, handler)

    assert isinstance(first, ToolMessage)
    assert isinstance(duplicate, ToolMessage)
    assert duplicate.content == "deployment does not exist"
    assert attempts == 1


@pytest.mark.asyncio
async def test_closed_mcp_session_is_retried_for_read_only_tool() -> None:
    middleware = ReliableToolMiddleware(
        executor=ReliableToolExecutor(
            journal=MemoryExecutionJournal(),
            retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0),
        ),
        tool_servers={"query_metrics": "prometheus"},
    )
    request = ToolCallRequest(
        tool_call={"id": "call-closed", "name": "query_metrics", "args": {"query": "up"}},
        tool=_tool("query_metrics", {"readOnlyHint": True}),
        state={},
        runtime=ToolRuntime(
            state={},
            context=None,
            config={"metadata": {"run_id": "run-closed"}},
            stream_writer=lambda _: None,
            tool_call_id="call-closed",
            store=None,
            tools=[],
        ),
    )
    attempts = 0

    async def handler(_: ToolCallRequest) -> ToolMessage:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise McpError(ErrorData(code=CONNECTION_CLOSED, message="Connection closed"))
        return ToolMessage(content="up == 1", tool_call_id="call-closed")

    result = await middleware.awrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert result.content == "up == 1"
    assert attempts == 2


@pytest.mark.asyncio
async def test_closed_mcp_session_is_not_retried_for_unsafe_tool() -> None:
    middleware = ReliableToolMiddleware(
        executor=ReliableToolExecutor(
            journal=MemoryExecutionJournal(),
            retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0),
        ),
        tool_servers={"restart": "kubernetes"},
    )
    request = ToolCallRequest(
        tool_call={"id": "call-unsafe", "name": "restart", "args": {"deployment": "payment"}},
        tool=_tool("restart", {"destructiveHint": True}),
        state={},
        runtime=ToolRuntime(
            state={},
            context=None,
            config={"metadata": {"run_id": "run-unsafe"}},
            stream_writer=lambda _: None,
            tool_call_id="call-unsafe",
            store=None,
            tools=[],
        ),
    )
    attempts = 0

    async def handler(_: ToolCallRequest) -> ToolMessage:
        nonlocal attempts
        attempts += 1
        raise McpError(ErrorData(code=CONNECTION_CLOSED, message="Connection closed"))

    result = await middleware.awrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert "outcome is unknown" in str(result.content)
    assert attempts == 1
