"""AG-UI agent wrappers that keep stream failures inside the protocol."""

from __future__ import annotations

import logging
from typing import Any

from ag_ui.core import RunErrorEvent
from ops_pilot.errors import log_exception

logger = logging.getLogger(__name__)


class ResilientAGUIAgentMixin:
    """Convert uncaught AG-UI run exceptions into protocol error events."""

    async def run(self, input_data: Any):
        try:
            source = super().run(input_data)  # type: ignore[misc]
            controller = getattr(self, "_ops_pilot_run_controller", None)
            run_id = getattr(input_data, "run_id", None)
            events = controller.iterate(run_id, source) if controller is not None and run_id else source
            async for event in events:
                yield event
        except Exception as exc:  # noqa: BLE001 - protocol boundary: convert to RUN_ERROR.
            thread_id, run_id = _run_ids(self, input_data)
            descriptor = log_exception(
                logger,
                exc,
                event="agui.run_failed",
                thread_id=thread_id,
                run_id=run_id,
            )
            yield RunErrorEvent(message=descriptor.message, code=descriptor.code)


def create_resilient_agui_agent(
    agent_cls: type[Any],
    *,
    run_controller: Any | None = None,
    **kwargs: Any,
) -> Any:
    """Instantiate ``agent_cls`` with resilient streaming error handling."""

    resilient_cls = type(
        f"Resilient{agent_cls.__name__}",
        (ResilientAGUIAgentMixin, agent_cls),
        {},
    )
    agent = resilient_cls(**kwargs)
    agent._ops_pilot_run_controller = run_controller
    return agent


def _run_ids(agent: Any, input_data: Any) -> tuple[str | None, str | None]:
    active_run = getattr(agent, "active_run", None) or {}
    thread_id = active_run.get("thread_id") if isinstance(active_run, dict) else None
    run_id = active_run.get("id") if isinstance(active_run, dict) else None
    return (
        thread_id or getattr(input_data, "thread_id", None),
        run_id or getattr(input_data, "run_id", None),
    )
