"""Agent state schema for the shared DeepAgent runtime.

Extends deepagents' ``DeepAgentState`` with a ``storyline`` channel so the
correlation workflow's result reaches the frontend: it is part of the graph's
output schema, so AG-UI/CopilotKit forwards it as shared state (the
``storyline`` key the App panel reads). Without this key on the schema, an
emitted ``storyline`` would be filtered out of the state snapshot.
"""

from __future__ import annotations

from typing import Any

from deepagents.graph import DeepAgentState


class StorylineAgentState(DeepAgentState):
    """DeepAgentState + the ``storyline`` shared-state channel."""

    storyline: dict[str, Any] | None
