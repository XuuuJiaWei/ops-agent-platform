"""Deterministic telemetry replay tools for low-cost agent regression tests."""

from __future__ import annotations

import json
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from ops_pilot.config.paths import SERVICE_ROOT

REPLAY_FIXTURE_DIR = SERVICE_ROOT / "eval" / "replay"
_REPLAY_CASE: ContextVar[str | None] = ContextVar("ops_pilot_replay_case", default=None)


def activate_replay_case(case_id: str) -> Token[str | None]:
    """Bind one eval case to its telemetry fixture for the current async context."""

    if not case_id or "/" in case_id or "\\" in case_id or case_id.startswith("."):
        raise ValueError(f"Invalid replay case id: {case_id!r}")
    return _REPLAY_CASE.set(case_id)


def reset_replay_case(token: Token[str | None]) -> None:
    """Restore the previous replay binding."""

    _REPLAY_CASE.reset(token)


@tool
async def search_traces(query: str) -> str:
    """Search a deterministic replay of recent distributed traces for an incident.

    The query should describe the service, operation, error, or latency signal to
    investigate. Replay mode returns a recorded/synthetic telemetry snapshot bound
    to the current eval case instead of contacting a live Jaeger backend.
    """

    return _replay_tool("search_traces", {"query": query})


@tool
async def query(query: str) -> str:
    """Run a PromQL-style query against a deterministic replayed metric snapshot.

    Replay mode is intended for regression tests: it preserves the evidence an
    agent can observe while removing the cost and flakiness of a live Kubernetes
    cluster. The query text is included in the returned audit envelope.
    """

    return _replay_tool("query", {"query": query})


def get_replay_tools() -> list[Any]:
    """Return the reduced Jaeger/Prometheus-compatible tool surface used by replay evals."""

    return [search_traces, query]


def _replay_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    case_id = _REPLAY_CASE.get()
    if case_id is None:
        raise RuntimeError("Replay telemetry tool called without an active replay case.")

    fixture = _load_fixture(case_id)
    tools = fixture.get("tools")
    if not isinstance(tools, dict):
        raise RuntimeError(f"Replay fixture {case_id!r} is missing a tools mapping.")
    payload = tools.get(tool_name)
    if payload is None:
        payload = {
            "status": "no_signal",
            "summary": f"The replay snapshot contains no {tool_name} evidence for this case.",
        }

    return json.dumps(
        {
            "replay": True,
            "case_id": case_id,
            "origin": fixture.get("origin", "unknown"),
            "captured_at": fixture.get("captured_at"),
            "tool": tool_name,
            "arguments": arguments,
            "data": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _load_fixture(case_id: str) -> dict[str, Any]:
    path = _fixture_path(case_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Replay fixture not found for case {case_id!r}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Replay fixture is invalid JSON for case {case_id!r}: {path}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"Replay fixture root must be an object: {path}")
    if payload.get("case_id") != case_id:
        raise RuntimeError(f"Replay fixture case_id mismatch for {path}: {payload.get('case_id')!r}")
    if payload.get("schema_version") != 1:
        raise RuntimeError(f"Unsupported replay fixture schema for {path}: {payload.get('schema_version')!r}")
    return payload


def _fixture_path(case_id: str) -> Path:
    return REPLAY_FIXTURE_DIR / f"{case_id}.json"
