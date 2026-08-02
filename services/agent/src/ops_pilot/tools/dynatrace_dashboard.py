"""Agent-native Dynatrace dashboard tool.

The agent gathers observability data with the Dynatrace MCP tools, then calls
``render_dynatrace_dashboard`` to project a compact, normalized snapshot onto the
web "App" view. The projection is pushed to the frontend through CopilotKit
shared state (``copilotkit_emit_state``); no REST API or frontend polling is
involved. See apps/web/src/app/AgentNativeAppView.tsx for the consumer and
ops_pilot.agent.state.DynatraceDashboard for the contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

if TYPE_CHECKING:
    from ops_pilot.agent.state import (
        DashboardStatus,
        DynatraceDashboard,
        DynatraceMetric,
        DynatraceProblem,
        MetricTone,
    )

_VALID_TONES: frozenset[str] = frozenset({"normal", "warning", "danger", "success"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _coerce_tone(value: Any) -> MetricTone:
    text = str(value).strip().lower() if value is not None else ""
    return text if text in _VALID_TONES else "normal"  # type: ignore[return-value]


def _coerce_sparkline(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)):
        return None
    points: list[float] = []
    for item in value:
        try:
            points.append(float(item))
        except (TypeError, ValueError):
            continue
    return points or None


def _normalize_metric(raw: Any) -> DynatraceMetric | None:
    if not isinstance(raw, dict):
        return None
    key = raw.get("key") or raw.get("id") or raw.get("label")
    label = raw.get("label") or raw.get("name") or key
    value = raw.get("value")
    if key is None or label is None or value is None:
        return None
    metric: DynatraceMetric = {
        "key": str(key),
        "label": str(label),
        "value": str(value),
        "tone": _coerce_tone(raw.get("tone")),
    }
    unit = raw.get("unit")
    if unit is not None:
        metric["unit"] = str(unit)
    sparkline = _coerce_sparkline(raw.get("sparkline"))
    if sparkline is not None:
        metric["sparkline"] = sparkline
    return metric


def _normalize_problem(raw: Any) -> DynatraceProblem | None:
    if not isinstance(raw, dict):
        return None
    problem_id = raw.get("id") or raw.get("problemId") or raw.get("displayId")
    title = raw.get("title") or raw.get("name") or raw.get("summary")
    if problem_id is None or title is None:
        return None
    problem: DynatraceProblem = {
        "id": str(problem_id),
        "title": str(title),
        "severity": str(raw.get("severity") or raw.get("severityLevel") or "UNKNOWN"),
    }
    entity = raw.get("entity") or raw.get("entityName") or raw.get("impactedEntity")
    if entity is not None:
        problem["entity"] = str(entity)
    started_at = raw.get("started_at") or raw.get("startTime") or raw.get("start")
    if started_at is not None:
        problem["started_at"] = str(started_at)
    return problem


def build_dashboard_snapshot(
    *,
    focus_entity: str | None,
    time_window: str,
    metrics: list[Any] | None,
    problems: list[Any] | None,
    note: str | None = None,
    status: DashboardStatus = "ready",
) -> DynatraceDashboard:
    """Normalize agent-supplied findings into the frontend dashboard contract.

    Pure and side-effect free so it can be unit tested against raw payload shapes.
    """

    normalized_metrics = [m for m in (_normalize_metric(item) for item in (metrics or [])) if m]
    normalized_problems = [p for p in (_normalize_problem(item) for item in (problems or [])) if p]
    snapshot: DynatraceDashboard = {
        "generated_at": _now_iso(),
        "focus_entity": focus_entity,
        "time_window": time_window,
        "status": status,
        "metrics": normalized_metrics,
        "problems": normalized_problems,
    }
    if note:
        snapshot["note"] = note
    return snapshot


async def _emit_loading(config: RunnableConfig, snapshot: DynatraceDashboard) -> None:
    """Push an interim loading snapshot to the frontend for instant feedback.

    This is out-of-band (CopilotKit custom event). The authoritative snapshot is
    written into real graph state via the tool's returned Command so it survives
    the run's final STATE_SNAPSHOT — the interim emit alone would be overwritten.
    """

    try:
        from copilotkit.langgraph import copilotkit_emit_state
    except ImportError:
        return
    from ops_pilot.agent.state import DYNATRACE_DASHBOARD_STATE_KEY

    await copilotkit_emit_state(config, {DYNATRACE_DASHBOARD_STATE_KEY: snapshot})


def get_dynatrace_dashboard_tools() -> list[Any]:
    """Return the agent-native Dynatrace dashboard tool(s)."""

    @tool
    async def render_dynatrace_dashboard(
        focus_entity: str,
        time_window: str,
        metrics: list[dict] | None,
        problems: list[dict] | None,
        config: RunnableConfig,
        tool_call_id: Annotated[str, InjectedToolCallId],
        note: str | None = None,
    ) -> Command:
        """Render an observability dashboard in the app's "App" view.

        Call this after gathering data with the Dynatrace tools, to show the
        operator a live dashboard. Pass the service/entity you focused on, the
        time window (e.g. "last 2h"), the headline `metrics`, and any open
        `problems`.

        metrics: list of {key, label, value, unit?, tone?, sparkline?} where tone
            is one of normal|warning|danger|success.
        problems: list of {id, title, severity, entity?, started_at?}.
        note: optional short summary shown on the dashboard.
        """

        from ops_pilot.agent.state import DYNATRACE_DASHBOARD_STATE_KEY

        await _emit_loading(
            config,
            {"status": "loading", "focus_entity": focus_entity, "generated_at": _now_iso()},
        )
        snapshot = build_dashboard_snapshot(
            focus_entity=focus_entity,
            time_window=time_window,
            metrics=metrics,
            problems=problems,
            note=note,
        )
        summary = (
            f"Rendered Dynatrace dashboard for {focus_entity} ({time_window}): "
            f"{len(snapshot.get('metrics', []))} metrics, "
            f"{len(snapshot.get('problems', []))} problems."
        )
        # Write to real graph state so the value persists through the run's final
        # STATE_SNAPSHOT and is readable by the frontend via useAgent().agent.state.
        return Command(
            update={
                DYNATRACE_DASHBOARD_STATE_KEY: snapshot,
                "messages": [ToolMessage(content=summary, tool_call_id=tool_call_id)],
            }
        )

    return [render_dynatrace_dashboard]
