"""Official A2A AgentExecutor backed by the shared DeepAgent runtime."""

from __future__ import annotations

import logging
from typing import Protocol

from ops_pilot.errors import log_exception

logger = logging.getLogger(__name__)


class A2ARuntime(Protocol):
    async def ainvoke_text(
        self,
        text: str,
        *,
        protocol: str,
        thread_id: str | None = None,
        run_id: str | None = None,
        configurable: dict[str, object] | None = None,
        extra_metadata: dict[str, object] | None = None,
    ) -> str: ...

    async def cancel_run(self, run_id: str, *, reason: str = "cancel requested") -> bool: ...


def create_executor(runtime: A2ARuntime):
    """Create an official A2A SDK executor for the DeepAgent runtime."""

    from a2a.server.agent_execution import AgentExecutor
    from a2a.server.events import EventQueue
    from a2a.server.tasks import TaskUpdater
    from a2a.types import Part

    class DeepAgentA2AExecutor(AgentExecutor):
        async def execute(self, context, event_queue: EventQueue) -> None:
            task_id = context.task_id or "task"
            context_id = context.context_id or task_id
            updater = TaskUpdater(event_queue=event_queue, task_id=task_id, context_id=context_id)

            await updater.submit()
            await updater.start_work(message=updater.new_agent_message(parts=[Part(text="Processing request...")]))

            try:
                response = await runtime.ainvoke_text(
                    context.get_user_input(),
                    protocol="a2a",
                    thread_id=context_id,
                    run_id=task_id,
                    configurable={"a2a_task_id": task_id, "a2a_context_id": context_id},
                    extra_metadata={"a2a_task_id": task_id, "a2a_context_id": context_id},
                )
            except Exception as exc:  # noqa: BLE001 - protocol adapter must publish failure event.
                descriptor = log_exception(
                    logger,
                    exc,
                    event="a2a.task_failed",
                    task_id=task_id,
                    context_id=context_id,
                )
                await updater.failed(message=updater.new_agent_message(parts=[Part(text=descriptor.message)]))
                return

            await updater.add_artifact(
                parts=[Part(text=response)],
                name="response",
                last_chunk=True,
            )
            await updater.complete(message=updater.new_agent_message(parts=[Part(text=response)]))

        async def cancel(self, context, event_queue: EventQueue) -> None:
            task_id = context.task_id or "task"
            context_id = context.context_id or task_id
            updater = TaskUpdater(event_queue=event_queue, task_id=task_id, context_id=context_id)
            cancel_run = getattr(runtime, "cancel_run", None)
            if cancel_run is not None:
                await cancel_run(task_id, reason="A2A cancel request")
            await updater.cancel()

    return DeepAgentA2AExecutor()
