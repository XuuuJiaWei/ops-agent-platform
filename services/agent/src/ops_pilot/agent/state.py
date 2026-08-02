"""Shared state typing for the DeepAgent graph.

The graph builds on DeepAgents' built-in state schema. ``OpsPilotState`` extends
it with an agent-native Dynatrace dashboard: a compact, frontend-ready snapshot
the agent writes while investigating, and the web "App" view renders live via
CopilotKit shared state.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from deepagents.graph import DeepAgentState

# Key under which the dashboard snapshot lives in agent state. Kept in sync with
# the frontend contract in apps/web/src/app/dynatrace.ts.
DYNATRACE_DASHBOARD_STATE_KEY = "dynatrace_dashboard"

MetricTone = Literal["normal", "warning", "danger", "success"]
DashboardStatus = Literal["loading", "ready", "error"]


class MessageInput(TypedDict, total=False):
    messages: list[Any]


class DynatraceMetric(TypedDict, total=False):
    """A single headline metric tile (error rate, response time, ...)."""

    key: str
    label: str
    value: str
    unit: NotRequired[str | None]
    tone: NotRequired[MetricTone]
    sparkline: NotRequired[list[float] | None]


class DynatraceProblem(TypedDict, total=False):
    """An open Dynatrace problem surfaced on the dashboard."""

    id: str
    title: str
    severity: str
    entity: NotRequired[str]
    started_at: NotRequired[str]


class DynatraceDashboard(TypedDict, total=False):
    """Compact, normalized dashboard snapshot rendered by the frontend.

    The agent decides what this contains (which entity, window, anomalies); the
    frontend is a pure projection of it.
    """

    generated_at: str
    focus_entity: NotRequired[str | None]
    time_window: NotRequired[str]
    status: DashboardStatus
    metrics: NotRequired[list[DynatraceMetric]]
    problems: NotRequired[list[DynatraceProblem]]
    note: NotRequired[str]


class OpsPilotState(DeepAgentState):
    """DeepAgent state extended with the Dynatrace dashboard snapshot."""

    dynatrace_dashboard: NotRequired[DynatraceDashboard]
