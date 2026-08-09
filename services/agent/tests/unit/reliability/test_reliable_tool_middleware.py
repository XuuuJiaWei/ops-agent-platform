from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.tools import ToolRuntime
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage

from ops_pilot.reliability.execution import MemoryExecutionJournal, ReliableToolExecutor, RetryPolicy
from ops_pilot.reliability.middleware import ReliableToolMiddleware


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
        tool=SimpleNamespace(name="query_metrics", metadata={"readOnlyHint": True}),
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
        tool=SimpleNamespace(name="restart", metadata={"destructiveHint": True}),
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
