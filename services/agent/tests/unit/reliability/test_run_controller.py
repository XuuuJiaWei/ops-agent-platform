from __future__ import annotations

import asyncio

import pytest

from ops_pilot.reliability.execution import MemoryExecutionJournal, ReliableToolExecutor, ToolCall
from ops_pilot.reliability.run import RunController, RunStatus


@pytest.mark.asyncio
async def test_stop_during_slow_mcp_call_cancels_run_before_dangerous_tool() -> None:
    controller = RunController()
    journal = MemoryExecutionJournal()
    executor = ReliableToolExecutor(journal=journal)
    slow_tool_entered = asyncio.Event()
    actions: list[str] = []

    async def workflow() -> None:
        async def slow_query() -> str:
            actions.append("slow-query-started")
            slow_tool_entered.set()
            await asyncio.Event().wait()
            return "unreachable"

        await executor.execute(
            ToolCall(
                run_id="run-stop",
                tool_call_id="slow-call",
                tool_name="slow_query",
                arguments={},
                dependency="prometheus-mcp",
                retry_safe=True,
            ),
            slow_query,
        )
        actions.append("dangerous-tool-executed")

    task = asyncio.create_task(controller.run("run-stop", workflow))
    await slow_tool_entered.wait()

    assert await controller.cancel("run-stop", reason="user clicked Stop") is True
    with pytest.raises(asyncio.CancelledError):
        await task

    assert controller.snapshot("run-stop").status is RunStatus.CANCELLED
    assert actions == ["slow-query-started"]


@pytest.mark.asyncio
async def test_run_deadline_cancels_work_and_records_terminal_state() -> None:
    controller = RunController(default_deadline_seconds=0.01)

    async def never_finishes() -> None:
        await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        await controller.run("run-deadline", never_finishes)

    snapshot = controller.snapshot("run-deadline")
    assert snapshot.status is RunStatus.DEADLINE_EXCEEDED
    assert snapshot.error == "deadline exceeded after 0.01s"
