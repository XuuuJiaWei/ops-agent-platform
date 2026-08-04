"""AG-UI agent wrappers that keep stream failures inside the protocol."""

from __future__ import annotations

import logging
from typing import Any

from ag_ui.core import EventType, RunErrorEvent, RunFinishedEvent

from ops_pilot.api.errors import stream_error_payload

logger = logging.getLogger(__name__)


class ResilientAGUIAgentMixin:
    """Convert uncaught AG-UI run exceptions into protocol error events."""

    async def run(self, input_data: Any):
        yielded_finished = False
        try:
            async for event in super().run(input_data):  # type: ignore[misc]
                yielded_finished = yielded_finished or getattr(event, "type", None) == EventType.RUN_FINISHED
                yield event
        except Exception as exc:  # noqa: BLE001 - protocol boundary: convert to RUN_ERROR.
            thread_id, run_id = _run_ids(self, input_data)
            logger.exception(
                "AG-UI run failed thread_id=%s run_id=%s",
                thread_id,
                run_id,
                exc_info=exc,
            )
            payload = stream_error_payload(exc)
            yield RunErrorEvent(message=payload["message"], code=payload["code"])
            if not yielded_finished and thread_id and run_id:
                yield RunFinishedEvent(thread_id=thread_id, run_id=run_id)


def create_resilient_agui_agent(agent_cls: type[Any], **kwargs: Any) -> Any:
    """Instantiate ``agent_cls`` with resilient streaming error handling."""

    resilient_cls = type(
        f"Resilient{agent_cls.__name__}",
        (ResilientAGUIAgentMixin, agent_cls),
        {},
    )
    return resilient_cls(**kwargs)


def _run_ids(agent: Any, input_data: Any) -> tuple[str | None, str | None]:
    active_run = getattr(agent, "active_run", None) or {}
    thread_id = active_run.get("thread_id") if isinstance(active_run, dict) else None
    run_id = active_run.get("id") if isinstance(active_run, dict) else None
    return (
        thread_id or getattr(input_data, "thread_id", None),
        run_id or getattr(input_data, "run_id", None),
    )
