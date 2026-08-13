from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from ops_pilot.eval import runner


@dataclass
class _Trace:
    text: str = "done"

    def as_output(self) -> dict[str, object]:
        return {
            "final_text": self.text,
            "tool_calls": [],
            "steps": 1,
            "latency_s": 0.0,
            "error": None,
        }


@pytest.mark.asyncio
async def test_eval_timeout_cancels_and_awaits_an_isolated_invocation_task() -> None:
    caller_task = asyncio.current_task()

    class Runtime:
        invocation_task: asyncio.Task | None = None
        cleanup_task: asyncio.Task | None = None
        cleaned_up = asyncio.Event()

        received_deadline: float | None = None

        async def ainvoke_trace(self, *_args, deadline_seconds=None, **_kwargs) -> _Trace:
            self.received_deadline = deadline_seconds
            self.invocation_task = asyncio.current_task()
            try:
                async with asyncio.timeout(deadline_seconds):
                    await asyncio.sleep(10)
            finally:
                self.cleanup_task = asyncio.current_task()
                await asyncio.sleep(0)
                self.cleaned_up.set()
            raise AssertionError("slow invocation unexpectedly completed")

    runtime = Runtime()
    task = runner._build_task(runtime, run_name="timeout-test")

    output = await task(item={"input": "slow", "metadata": {"id": "slow", "timeout_s": 0.1}})

    assert output["error_type"] == "TimeoutError"
    assert runtime.cleaned_up.is_set()
    assert runtime.invocation_task is runtime.cleanup_task
    assert runtime.invocation_task is not caller_task
    assert runtime.received_deadline == 0.1


@pytest.mark.asyncio
async def test_eval_task_dispatches_runtime_work_to_its_owner_loop() -> None:
    owner_loop = asyncio.get_running_loop()

    class Runtime:
        invocation_loop: asyncio.AbstractEventLoop | None = None
        received_deadline: float | None = None

        async def ainvoke_trace(self, *_args, deadline_seconds=None, **_kwargs) -> _Trace:
            self.invocation_loop = asyncio.get_running_loop()
            self.received_deadline = deadline_seconds
            return _Trace()

    runtime = Runtime()
    task = runner._build_task(runtime, run_name="loop-test")

    def invoke_from_worker_thread() -> dict[str, object]:
        return asyncio.run(task(item={"input": "hello", "metadata": {"id": "hello", "timeout_s": 1}}))

    output = await asyncio.to_thread(invoke_from_worker_thread)

    assert output["final_text"] == "done"
    assert runtime.invocation_loop is owner_loop
    assert runtime.received_deadline == 1


@pytest.mark.asyncio
async def test_close_runtime_prefers_aclose() -> None:
    class Runtime:
        async_closed = False
        sync_closed = False

        async def aclose(self) -> None:
            self.async_closed = True

        def close(self) -> None:
            self.sync_closed = True

    runtime = Runtime()
    await runner._close_runtime(runtime)

    assert runtime.async_closed is True
    assert runtime.sync_closed is False


@pytest.mark.asyncio
async def test_fixed_output_case_skips_the_agent() -> None:
    class Runtime:
        invoked = False

        async def ainvoke_trace(self, *_args, **_kwargs):
            self.invoked = True
            return _Trace()

    runtime = Runtime()
    task = runner._build_task(runtime, run_name="sentinel-test")

    output = await task(
        item={
            "input": "PagerDuty alert...",
            "metadata": {"id": "__sentinel", "fixed_output": "canned judge input", "timeout_s": 5},
        }
    )

    assert runtime.invoked is False  # agent never ran
    assert output["final_text"] == "canned judge input"
    assert output["steps"] == 0
    assert output["error"] is None


def test_evaluate_gates_pass_when_metrics_absent() -> None:
    from langfuse import Evaluation
    from langfuse.experiment import ExperimentResult

    result = ExperimentResult(
        name="t",
        run_name="t",
        description="t",
        item_results=[],
        run_evaluations=[Evaluation(name="pass_rate", value=1.0)],
        experiment_id="t",
    )

    # No safety / calibration / infra metrics present → nothing to gate → pass.
    assert runner._evaluate_gates(result, min_pass_rate=None) == 0
