"""Storyline data structures (backend side of the frontend contract).

These mirror ``apps/web/src/app/storyline.ts`` and design doc §3.1. ``as_dict``
produces exactly the shape the CopilotKit ``storyline`` shared-state key
expects, so the App panel can render it without transformation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

StorylineSource = Literal[
    "dynatrace_problem",
    "dynatrace_event",
    "dynatrace_metric",
    "kibana_log",
]

StorylineSeverity = Literal["info", "warn", "error", "critical"]
StorylineRole = Literal["trigger", "propagation", "symptom", "context"]
StorylineStatus = Literal["loading", "ready", "error"]


@dataclass(frozen=True)
class StorylineNode:
    """One signal on the timeline, from any source, normalized."""

    ts: int  # UTC epoch ms — unified time base.
    source: str  # StorylineSource, kept open for forward-compat.
    kind: str  # e.g. "LongJAVAGCTime" / "log.ERROR".
    title: str
    entity_id: str | None = None
    entity_name: str | None = None
    severity: str = "info"
    role: str = "context"
    evidence: dict[str, Any] = field(default_factory=dict)
    deep_link: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "source": self.source,
            "kind": self.kind,
            "title": self.title,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "severity": self.severity,
            "role": self.role,
            "evidence": self.evidence,
            "deep_link": self.deep_link,
        }


@dataclass(frozen=True)
class Storyline:
    """The correlated fault storyline — final workflow product."""

    status: StorylineStatus = "ready"
    window: tuple[int, int] | None = None
    entities: tuple[str, ...] = field(default_factory=tuple)
    nodes: tuple[StorylineNode, ...] = field(default_factory=tuple)
    root_cause: StorylineNode | None = None
    narrative: str = ""
    confidence: float | None = None
    gaps: tuple[str, ...] = field(default_factory=tuple)
    generated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "window": list(self.window) if self.window else None,
            "entities": list(self.entities),
            "nodes": [node.as_dict() for node in self.nodes],
            "root_cause": self.root_cause.as_dict() if self.root_cause else None,
            "narrative": self.narrative,
            "confidence": self.confidence,
            "gaps": list(self.gaps),
            "generated_at": self.generated_at,
        }
