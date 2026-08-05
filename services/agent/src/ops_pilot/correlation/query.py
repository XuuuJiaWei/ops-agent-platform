"""StorylineQuery — unified input contract for the three trigger modes.

Design doc §2.1/§2.2: mode A (entity-axis), mode B (problem-axis), mode C
(time-window-axis) all normalize into the same ``StorylineQuery``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StorylineQuery:
    # Time window (relative like "now-30m" or absolute ISO / epoch-ms string).
    time_from: str = "now-30m"
    time_to: str = "now"

    # Entity scope (mode A required; mode B/C may derive it).
    entity_ids: tuple[str, ...] = field(default_factory=tuple)
    service_names: tuple[str, ...] = field(default_factory=tuple)

    # Convergence filters (aligned to real Dynatrace fields).
    management_zones: tuple[str, ...] = field(default_factory=tuple)
    entity_tags: tuple[str, ...] = field(default_factory=tuple)

    # Seed (mode B).
    seed_problem_id: str | None = None

    # Budget caps — keep the LLM seeing tens of nodes, not millions.
    # max_log_lines stays <=50: the Kibana MCP server enforces a ~20k-token
    # response cap, and 100 istio log lines exceed it (see kibana adapter).
    max_problems: int = 50
    max_events: int = 200
    max_log_lines: int = 50

    @property
    def mode(self) -> str:
        """Trigger mode inferred from which fields are populated."""

        if self.seed_problem_id:
            return "B"
        if self.entity_ids or self.service_names:
            return "A"
        return "C"


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item not in (None, ""))
    return ()


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_query(payload: Mapping[str, Any] | StorylineQuery) -> StorylineQuery:
    """Coerce a loose mapping (tool args / API body) into a StorylineQuery."""

    if isinstance(payload, StorylineQuery):
        return payload
    if not isinstance(payload, Mapping):
        return StorylineQuery()

    return StorylineQuery(
        time_from=str(payload.get("time_from") or "now-30m"),
        time_to=str(payload.get("time_to") or "now"),
        entity_ids=_as_tuple(payload.get("entity_ids")),
        service_names=_as_tuple(payload.get("service_names")),
        management_zones=_as_tuple(payload.get("management_zones")),
        entity_tags=_as_tuple(payload.get("entity_tags")),
        seed_problem_id=(str(payload["seed_problem_id"]) if payload.get("seed_problem_id") else None),
        max_problems=_as_int(payload.get("max_problems"), 50),
        max_events=_as_int(payload.get("max_events"), 200),
        max_log_lines=_as_int(payload.get("max_log_lines"), 50),
    )
