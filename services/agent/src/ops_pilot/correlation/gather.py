"""Phase one: gather (convergence) — deterministic, no LLM.

Two parallel nodes, one per source. Each writes only its own state key
(``raw_dynatrace`` / ``raw_kibana``) so the fan-out is concurrency-safe without
reducers (design §4.5). Nodes are built as closures over the runtime
``ToolRegistry`` since MCP tools are loaded dynamically at startup.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ops_pilot.correlation.adapters import ToolRegistry
from ops_pilot.correlation.adapters.dynatrace import gather_dynatrace_nodes
from ops_pilot.correlation.adapters.kibana import gather_kibana_nodes
from ops_pilot.correlation.query import StorylineQuery

StateUpdate = dict[str, Any]
Node = Callable[[dict[str, Any]], Awaitable[StateUpdate]]


def _query_from_state(state: dict[str, Any]) -> StorylineQuery:
    query = state.get("query")
    if isinstance(query, StorylineQuery):
        return query
    return StorylineQuery()


def make_gather_dynatrace(registry: ToolRegistry) -> Node:
    async def gather_dynatrace(state: dict[str, Any]) -> StateUpdate:
        query = _query_from_state(state)
        nodes, gaps = await gather_dynatrace_nodes(registry, query)
        return {"raw_dynatrace": nodes, "gaps_dt": gaps}

    return gather_dynatrace


def make_gather_kibana(registry: ToolRegistry) -> Node:
    async def gather_kibana(state: dict[str, Any]) -> StateUpdate:
        query = _query_from_state(state)
        nodes, gaps = await gather_kibana_nodes(registry, query)
        return {"raw_kibana": nodes, "gaps_kb": gaps}

    return gather_kibana
