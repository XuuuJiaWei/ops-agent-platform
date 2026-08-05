"""Phase two: align — deterministic, no LLM.

Merge both sources' normalized nodes into one timeline sorted by ``ts`` (UTC
epoch ms). Pure data transformation (design §4.2).
"""

from __future__ import annotations

from typing import Any

from ops_pilot.correlation.models import StorylineNode


def _coerce_nodes(value: Any) -> list[StorylineNode]:
    if isinstance(value, list):
        return [node for node in value if isinstance(node, StorylineNode)]
    return []


def align_nodes(state: dict[str, Any]) -> dict[str, Any]:
    """Merge raw_dynatrace + raw_kibana into a single time-sorted timeline."""

    merged = _coerce_nodes(state.get("raw_dynatrace")) + _coerce_nodes(state.get("raw_kibana"))
    merged.sort(key=lambda node: node.ts)

    gaps: list[str] = []
    for key in ("gaps_dt", "gaps_kb"):
        value = state.get(key)
        if isinstance(value, list):
            gaps.extend(str(item) for item in value)

    return {"nodes": merged, "gaps": gaps}
