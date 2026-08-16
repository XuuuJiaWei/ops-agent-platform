from __future__ import annotations

import logging

import pytest
from ag_ui.core import EventType
from ag_ui.core.types import RunAgentInput
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ops_pilot.errors import configure_exception_logging, log_exception, public_error_payload

from ops_pilot_platform.agui.resilient import create_resilient_agui_agent
from ops_pilot_platform.api.errors import register_exception_handlers


def test_global_exception_handler_returns_stable_json_response(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    with caplog.at_level(logging.ERROR, logger="ops_pilot_platform.api.errors"):
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
    records = [record for record in caplog.records if record.getMessage().startswith("http.request_failed")]
    assert len(records) == 1
    assert records[0].exc_info is not None


def test_request_id_is_added_to_successful_responses() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/ok", headers={"x-request-id": "req-456"})

    assert response.headers["x-request-id"] == "req-456"


def test_operational_http_error_returns_503_without_a_traceback(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/dependency")
    async def dependency() -> None:
        raise ConnectionError("connection reset")

    with caplog.at_level(logging.WARNING, logger="ops_pilot_platform.api.errors"):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/dependency")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "dependency_unavailable"
    records = [record for record in caplog.records if record.getMessage().startswith("http.request_failed")]
    assert len(records) == 1
    assert records[0].exc_info is None


def test_sandbox_not_found_errors_are_classified_as_recoverable_runtime_errors() -> None:
    payload = public_error_payload(RuntimeError("Failed to run command. Status code: 404: sandbox not found"))

    assert payload == {
        "code": "sandbox_unavailable",
        "message": (
            "The sandbox expired or became unavailable. Please retry; a fresh sandbox will be created automatically."
        ),
    }


def test_model_connection_errors_are_classified_as_model_unavailable() -> None:
    class APIConnectionError(ConnectionError):
        pass

    try:
        raise ConnectionError("SSL/TLS alert handshake failure")
    except ConnectionError as cause:
        error = APIConnectionError("Connection error.")
        error.__cause__ = cause

    assert public_error_payload(error) == {
        "code": "model_unavailable",
        "message": (
            "The configured AI model is temporarily unreachable. "
            "Check the model endpoint, proxy, and TLS settings, then retry."
        ),
    }


def test_operational_failures_log_once_without_a_traceback(caplog: pytest.LogCaptureFixture) -> None:
    class APIConnectionError(ConnectionError):
        pass

    error = APIConnectionError("Connection error.")

    with caplog.at_level(logging.WARNING, logger="test.error_policy"):
        log_exception(
            logging.getLogger("test.error_policy"),
            error,
            event="agui.run_failed",
            run_id="run-1",
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].exc_info is None
    assert "code=model_unavailable" in caplog.records[0].getMessage()


def test_mcp_transport_filter_collapses_expected_connection_tracebacks(caplog: pytest.LogCaptureFixture) -> None:
    class ConnectError(ConnectionError):
        pass

    configure_exception_logging()
    logger = logging.getLogger("mcp.client.streamable_http")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        try:
            raise ConnectError("connection reset")
        except ConnectError:
            logger.exception("Error in post_writer")

    records = [record for record in caplog.records if record.getMessage().startswith("mcp.transport_failed")]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is None
    assert "code=dependency_unavailable" in records[0].getMessage()


def test_mcp_transport_filter_preserves_unexpected_tracebacks(caplog: pytest.LogCaptureFixture) -> None:
    configure_exception_logging()
    logger = logging.getLogger("mcp.client.streamable_http")

    with caplog.at_level(logging.ERROR, logger=logger.name):
        try:
            raise RuntimeError("broken SDK invariant")
        except RuntimeError:
            logger.exception("Error in post_writer")

    records = [record for record in caplog.records if record.getMessage() == "Error in post_writer"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None


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

    assert [event.type for event in events] == [EventType.RUN_ERROR]
    assert events[0].code == "sandbox_unavailable"
