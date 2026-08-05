"""Multi-source fault storyline correlation.

Correlates Dynatrace problems/events/metrics with Kibana logs in one time
window, producing a causally-ordered fault storyline. See
``docs/design/multi-source-storyline-correlation.md`` for the full design.

The workflow is a deterministic LangGraph ``StateGraph`` (gather → align →
correlate → narrate); only the ``narrate`` node uses an LLM. Build it with
``build_storyline_graph(tools, model)`` and drive it via ``run_storyline``.
"""

from __future__ import annotations

from ops_pilot.correlation.models import Storyline, StorylineNode
from ops_pilot.correlation.orchestrator import build_storyline_graph, run_storyline
from ops_pilot.correlation.query import StorylineQuery, normalize_query

__all__ = [
    "Storyline",
    "StorylineNode",
    "StorylineQuery",
    "build_storyline_graph",
    "normalize_query",
    "run_storyline",
]
