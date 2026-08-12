from __future__ import annotations

import pytest
from ag_ui.core import EventType
from ag_ui.core.types import RunAgentInput
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ops_pilot.agui.resilient import create_resilient_agui_agent
from ops_pilot.api.errors import register_exception_handlers, stream_error_payload


def test_global_exception_handler_returns_stable_json_response() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom", headers={"x-request-id": "req-123"})

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "req-123"
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Unexpected server error.",
            "request_id": "req-123",
        }
    }


def test_sandbox_not_found_errors_are_classified_as_recoverable_runtime_errors() -> None:
    payload = stream_error_payload(RuntimeError("Failed to run command. Status code: 404: sandbox not found"))

    assert payload == {
        "code": "sandbox_unavailable",
        "message": (
            "The sandbox expired or became unavailable. Please retry; a fresh sandbox will be created automatically."
        ),
    }


@pytest.mark.asyncio
async def test_resilient_agui_agent_converts_stream_exceptions_to_run_error_events() -> None:
    class RaisingAgent:
        active_run = {"thread_id": "thread-1", "id": "run-1"}

        async def run(self, _: RunAgentInput):
            raise RuntimeError("Sandbox 'sandbox-123' not found")
            yield  # pragma: no cover

    agent = create_resilient_agui_agent(RaisingAgent)
    input_data = RunAgentInput(
        thread_id="thread-1",
        run_id="run-1",
        state={},
        messages=[],
        tools=[],
        context=[],
        forwarded_props={},
    )

    events = [event async for event in agent.run(input_data)]

    assert [event.type for event in events] == [EventType.RUN_ERROR, EventType.RUN_FINISHED]
    assert events[0].code == "sandbox_unavailable"
