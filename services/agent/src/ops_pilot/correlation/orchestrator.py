"""StateGraph orchestrator + entrypoint for the storyline workflow.

Inner layer: a deterministic ``StateGraph`` (gather → align → correlate →
narrate), parallel gather fan-out joined at ``align``. Outer layer:
``run_storyline`` normalizes input and returns the ``Storyline`` dict. See
design §4.5 / §5.4.

MCP tools and the chat model are injected via ``build_storyline_graph`` because
they are only known at runtime (loaded at startup). ``build_storyline_tool``
wraps the graph as a single ``@tool`` for the deep agent's conversational entry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from langchain_core.tools import InjectedToolCallId
from langgraph.types import Command
from typing_extensions import TypedDict

from ops_pilot.correlation.adapters import ToolRegistry
from ops_pilot.correlation.align import align_nodes
from ops_pilot.correlation.correlate import correlate_scores
from ops_pilot.correlation.gather import make_gather_dynatrace, make_gather_kibana
from ops_pilot.correlation.models import Storyline
from ops_pilot.correlation.narrate import make_narrate
from ops_pilot.correlation.query import StorylineQuery, normalize_query


class StorylineState(TypedDict, total=False):
    query: StorylineQuery
    raw_dynatrace: list[Any]
    raw_kibana: list[Any]
    gaps_dt: list[str]
    gaps_kb: list[str]
    nodes: list[Any]
    scored: list[Any]
    gaps: list[str]
    root_cause: Any
    storyline: Storyline


def build_storyline_graph(tools: Sequence[Any], model: Any) -> Any:
    """Compile the deterministic storyline StateGraph.

    ``tools`` are the runtime-loaded MCP tools; ``model`` is the SAP chat model
    (same one the main agent uses) — only the narrate node calls it.
    """

    from langgraph.graph import END, START, StateGraph

    registry = ToolRegistry(tools)

    builder = StateGraph(StorylineState)
    builder.add_node("gather_dt", make_gather_dynatrace(registry))
    builder.add_node("gather_kb", make_gather_kibana(registry))
    builder.add_node("align", align_nodes)
    builder.add_node("correlate", correlate_scores)
    builder.add_node("narrate", make_narrate(model))

    # Parallel fan-out from START; align has two in-edges → auto barrier.
    builder.add_edge(START, "gather_dt")
    builder.add_edge(START, "gather_kb")
    builder.add_edge("gather_dt", "align")
    builder.add_edge("gather_kb", "align")
    builder.add_edge("align", "correlate")
    builder.add_edge("correlate", "narrate")
    builder.add_edge("narrate", END)

    return builder.compile()


async def run_storyline(
    payload: Mapping[str, Any] | StorylineQuery,
    *,
    tools: Sequence[Any],
    model: Any,
) -> dict[str, Any]:
    """Outer entry: normalize input, run the graph, return the Storyline dict.

    Used by both the conversational tool and any standalone (A2A / API / eval)
    caller — one implementation, two front doors (design §5.4).
    """

    query = normalize_query(payload)
    graph = build_storyline_graph(tools, model)
    result = await graph.ainvoke({"query": query})
    storyline = result.get("storyline")
    if isinstance(storyline, Storyline):
        return storyline.as_dict()
    return Storyline(status="error", narrative="Workflow produced no storyline.").as_dict()


def build_storyline_tool(tools: Sequence[Any], model: Any) -> Any:
    """Wrap the storyline workflow as a single deep-agent tool.

    The deep agent calls this when a user asks to correlate a fault; the tool
    runs the deterministic graph and returns a ``Command`` that both writes the
    Storyline into the ``storyline`` shared-state key (so the frontend App panel
    renders it via AG-UI/CopilotKit) and returns a compact text summary to the
    model.
    """

    from langchain_core.messages import ToolMessage
    from langchain_core.tools import tool

    @tool
    async def build_storyline(
        tool_call_id: Annotated[str, InjectedToolCallId],
        time_from: str = "now-30m",
        time_to: str = "now",
        entity_ids: list[str] | None = None,
        service_names: list[str] | None = None,
        management_zones: list[str] | None = None,
        seed_problem_id: str | None = None,
    ) -> Command:
        """Correlate Dynatrace problems/events with Kibana logs in one time window into a fault storyline.

        Use for questions like "what happened to <service> in the last 30 minutes?"
        or "explain problem <P-id>". Provide service_names (Kubernetes app label)
        to pull matching Kibana logs, and/or entity_ids (Dynatrace entityId) and
        management_zones to scope Dynatrace. The full timeline renders in the App
        panel; this returns a short summary for the conversation.
        """

        storyline = await run_storyline(
            {
                "time_from": time_from,
                "time_to": time_to,
                "entity_ids": entity_ids or [],
                "service_names": service_names or [],
                "management_zones": management_zones or [],
                "seed_problem_id": seed_problem_id,
            },
            tools=tools,
            model=model,
        )
        return Command(
            update={
                "storyline": storyline,
                "messages": [ToolMessage(_summarize(storyline), tool_call_id=tool_call_id)],
            }
        )

    return build_storyline


def _summarize(storyline: dict[str, Any]) -> str:
    """Compact text summary of a storyline dict for the model/conversation."""

    node_count = len(storyline.get("nodes") or [])
    root = storyline.get("root_cause") or {}
    gaps = storyline.get("gaps") or []
    parts = [
        f"Built storyline: {node_count} correlated signal(s).",
    ]
    if root:
        confidence = storyline.get("confidence")
        conf = f" ({round(confidence * 100)}% confidence)" if isinstance(confidence, (int, float)) else ""
        parts.append(f"Likely root cause: {root.get('title')}{conf}.")
    if storyline.get("narrative"):
        parts.append(str(storyline["narrative"]))
    if gaps:
        parts.append(f"Coverage gaps: {len(gaps)}.")
    parts.append("Full timeline is shown in the App panel.")
    return " ".join(parts)
