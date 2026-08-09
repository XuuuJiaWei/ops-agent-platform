"""Official A2A AgentExecutor backed by the shared DeepAgent runtime."""

from __future__ import annotations

import logging

from ops_pilot.agent.runtime import AgentRuntime
from ops_pilot.config.settings import Settings

logger = logging.getLogger(__name__)


def create_executor(runtime: AgentRuntime, settings: Settings):
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
                    a2a_task_id=task_id,
                    a2a_context_id=context_id,
                )
            except Exception as exc:  # noqa: BLE001 - protocol adapter must publish failure event.
                logger.exception("A2A task failed")
                await updater.failed(message=updater.new_agent_message(parts=[Part(text=_public_error(exc))]))
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


def _public_error(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__
