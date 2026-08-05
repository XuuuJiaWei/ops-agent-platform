"""Phase four: narrate — the only LLM node.

Takes the converged, scored timeline (tens of nodes, never millions) and asks
the model for a causal narrative + confidence. Everything structural is already
decided deterministically upstream; the LLM only writes prose and picks a
confidence, and is told to say so when evidence is thin (design §4.4).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from ops_pilot.correlation.models import Storyline, StorylineNode

Node = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_SYSTEM_PROMPT = (
    "You are an SRE correlation assistant. You are given a pre-correlated, "
    "time-ordered list of signals from Dynatrace and Kibana, each already "
    "tagged with a causal role (trigger/propagation/symptom/context). Do NOT "
    "invent correlations beyond what the roles imply. Write a concise causal "
    "narrative (<=6 sentences) explaining the fault from trigger to symptom. "
    "If evidence is thin or sources are missing, say so plainly. Respond with "
    'JSON: {"narrative": str, "confidence": float 0-1}.'
)


def _node_brief(node: StorylineNode) -> dict[str, Any]:
    return {
        "ts": node.ts,
        "source": node.source,
        "kind": node.kind,
        "title": node.title,
        "entity": node.entity_name,
        "severity": node.severity,
        "role": node.role,
    }


def _window_of(nodes: list[StorylineNode]) -> tuple[int, int] | None:
    if not nodes:
        return None
    times = [n.ts for n in nodes]
    return (min(times), max(times))


def _entities_of(nodes: list[StorylineNode]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for node in nodes:
        name = node.entity_name
        if name and name not in seen:
            seen[name] = None
    return tuple(seen.keys())


def _parse_llm_json(text: str) -> tuple[str, float | None]:
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return text.strip(), None
    narrative = str(data.get("narrative", "")).strip()
    confidence = data.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    return narrative, confidence


def _extract_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [item.get("text", "") if isinstance(item, dict) else str(item) for item in content]
        return "\n".join(part for part in parts if part)
    return str(content)


def make_narrate(model: Any) -> Node:
    async def narrate(state: dict[str, Any]) -> dict[str, Any]:
        scored = state.get("scored")
        nodes = [n for n in scored if isinstance(n, StorylineNode)] if isinstance(scored, list) else []
        root_cause = state.get("root_cause")
        gaps = state.get("gaps") if isinstance(state.get("gaps"), list) else []

        narrative = ""
        confidence: float | None = None
        status = "ready"

        if nodes:
            prompt_payload = {
                "trigger": _node_brief(root_cause) if isinstance(root_cause, StorylineNode) else None,
                "timeline": [_node_brief(n) for n in nodes],
                "gaps": gaps,
            }
            try:
                response = await model.ainvoke(
                    [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
                    ]
                )
                narrative, confidence = _parse_llm_json(_extract_text(response))
            except Exception:  # noqa: BLE001 - narration failure must not fail the workflow.
                narrative = "Correlation completed but narrative generation failed; see the timeline below."
                status = "error"
        else:
            narrative = "No correlated signals found in this window."

        storyline = Storyline(
            status=status,
            window=_window_of(nodes),
            entities=_entities_of(nodes),
            nodes=tuple(nodes),
            root_cause=root_cause if isinstance(root_cause, StorylineNode) else None,
            narrative=narrative,
            confidence=confidence,
            gaps=tuple(str(g) for g in gaps),
            generated_at=None,
        )
        return {"storyline": storyline}

    return narrate
