from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from ops_pilot.reliability.execution import (
    CircuitBreakerPolicy,
    CircuitOpenError,
    ExecutionRecord,
    ExecutionStatus,
    IndeterminateToolError,
    MemoryExecutionJournal,
    ReliableToolExecutor,
    RetryPolicy,
    ToolCall,
    TransientToolError,
)


@pytest.mark.asyncio
async def test_completed_tool_call_is_reused_after_response_is_lost() -> None:
    journal = MemoryExecutionJournal()
    executor = ReliableToolExecutor(journal=journal)
    side_effects: list[str] = []

    async def create_incident() -> dict[str, str]:
        side_effects.append("INC-1")
        return {"incident_id": "INC-1"}

    call = ToolCall(
        run_id="run-1",
        tool_call_id="call-1",
        tool_name="create_incident",
        arguments={"summary": "checkout unavailable"},
        dependency="incident-mcp",
        retry_safe=False,
    )

    first = await executor.execute(call, create_incident)
    # Simulate the transport dropping after execute() durably stored success but
    # before the caller received the response. A recovered runtime sees the same
    # journal and the same model-issued tool call ID.
    recovered = ReliableToolExecutor(journal=journal)
    second = await recovered.execute(call, _must_not_run())

    assert first.value == {"incident_id": "INC-1"}
    assert first.reused is False
    assert second.value == {"incident_id": "INC-1"}
    assert second.reused is True
    assert second.attempt == 1
    assert side_effects == ["INC-1"]


def _must_not_run() -> Callable[[], Awaitable[dict[str, str]]]:
    async def operation() -> dict[str, str]:
        raise AssertionError("a completed side effect must not execute twice")

    return operation


@pytest.mark.asyncio
async def test_retry_safe_tool_retries_503_and_records_attempt() -> None:
    executor = ReliableToolExecutor(
        journal=MemoryExecutionJournal(),
        retry_policy=RetryPolicy(max_attempts=3, initial_backoff_seconds=0),
    )
    invocations = 0

    async def query_metrics() -> dict[str, float]:
        nonlocal invocations
        invocations += 1
        if invocations == 1:
            raise TransientToolError("MCP server returned 503", status_code=503)
        return {"error_rate": 0.42}

    outcome = await executor.execute(
        ToolCall(
            run_id="run-2",
            tool_call_id="call-2",
            tool_name="query_metrics",
            arguments={"query": "rate(errors_total[5m])"},
            dependency="prometheus-mcp",
            retry_safe=True,
        ),
        query_metrics,
    )

    assert outcome.value == {"error_rate": 0.42}
    assert outcome.attempt == 2
    assert invocations == 2


@pytest.mark.asyncio
async def test_concurrent_duplicate_tool_call_waits_and_reuses_first_result() -> None:
    executor = ReliableToolExecutor(journal=MemoryExecutionJournal())
    entered = asyncio.Event()
    release = asyncio.Event()
    invocations = 0

    async def slow_write() -> str:
        nonlocal invocations
        invocations += 1
        entered.set()
        await release.wait()
        return "updated"

    call = ToolCall(
        run_id="run-3",
        tool_call_id="call-3",
        tool_name="update_deployment",
        arguments={"replicas": 3},
        dependency="kubernetes-mcp",
        retry_safe=False,
    )
    first_task = asyncio.create_task(executor.execute(call, slow_write))
    await entered.wait()
    duplicate_task = asyncio.create_task(executor.execute(call, slow_write))
    await asyncio.sleep(0)
    release.set()
    first, duplicate = await asyncio.gather(first_task, duplicate_task)

    assert first.value == duplicate.value == "updated"
    assert first.reused is False
    assert duplicate.reused is True
    assert invocations == 1


@pytest.mark.asyncio
async def test_repeated_failures_open_only_the_failing_mcp_server_circuit() -> None:
    executor = ReliableToolExecutor(
        journal=MemoryExecutionJournal(),
        retry_policy=RetryPolicy(max_attempts=1),
        circuit_breaker_policy=CircuitBreakerPolicy(failure_threshold=2, recovery_timeout_seconds=60),
    )
    failed_server_invocations = 0

    async def unavailable() -> str:
        nonlocal failed_server_invocations
        failed_server_invocations += 1
        raise TransientToolError("MCP unavailable", status_code=503)

    for index in range(2):
        with pytest.raises(TransientToolError):
            await executor.execute(
                ToolCall(
                    run_id=f"run-fail-{index}",
                    tool_call_id=f"call-fail-{index}",
                    tool_name="query_logs",
                    arguments={},
                    dependency="opensearch-mcp",
                    retry_safe=True,
                ),
                unavailable,
            )

    with pytest.raises(CircuitOpenError):
        await executor.execute(
            ToolCall(
                run_id="run-open",
                tool_call_id="call-open",
                tool_name="query_logs",
                arguments={},
                dependency="opensearch-mcp",
                retry_safe=True,
            ),
            unavailable,
        )

    healthy = await executor.execute(
        ToolCall(
            run_id="run-healthy",
            tool_call_id="call-healthy",
            tool_name="query_metrics",
            arguments={},
            dependency="prometheus-mcp",
            retry_safe=True,
        ),
        _constant("healthy"),
    )

    assert healthy.value == "healthy"
    assert failed_server_invocations == 2


def _constant(value: str) -> Callable[[], Awaitable[str]]:
    async def operation() -> str:
        return value

    return operation


@pytest.mark.asyncio
async def test_ambiguous_failure_of_non_idempotent_write_becomes_unknown_without_retry() -> None:
    journal = MemoryExecutionJournal()
    executor = ReliableToolExecutor(journal=journal, retry_policy=RetryPolicy(max_attempts=3))
    invocations = 0

    async def connection_lost_after_write() -> str:
        nonlocal invocations
        invocations += 1
        raise IndeterminateToolError("connection closed before a response arrived")

    call = ToolCall(
        run_id="run-unknown",
        tool_call_id="call-unknown",
        tool_name="restart_production",
        arguments={"deployment": "checkout"},
        dependency="kubernetes-mcp",
        retry_safe=False,
    )

    with pytest.raises(IndeterminateToolError):
        await executor.execute(call, connection_lost_after_write)
    with pytest.raises(IndeterminateToolError):
        await executor.execute(call, _must_not_run())

    record = await journal.get(call)
    assert record is not None
    assert record.status is ExecutionStatus.UNKNOWN
    assert record.attempt == 1
    assert invocations == 1


@pytest.mark.asyncio
async def test_recovery_marks_orphaned_non_idempotent_execution_unknown() -> None:
    journal = MemoryExecutionJournal()
    call = ToolCall(
        run_id="run-orphaned",
        tool_call_id="call-orphaned",
        tool_name="create_incident",
        arguments={"summary": "latency"},
        dependency="incident-mcp",
        retry_safe=False,
    )
    await journal.put(ExecutionRecord(call=call, status=ExecutionStatus.RUNNING, attempt=1))

    with pytest.raises(IndeterminateToolError):
        await ReliableToolExecutor(journal=journal).execute(call, _must_not_run())

    record = await journal.get(call)
    assert record is not None
    assert record.status is ExecutionStatus.UNKNOWN
