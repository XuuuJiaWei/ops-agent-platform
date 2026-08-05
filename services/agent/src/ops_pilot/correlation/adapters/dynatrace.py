"""Dynatrace source adapter — problems/events into normalized StorylineNodes.

Wraps the runtime-loaded Dynatrace Managed MCP tools. Reality check (verified
against @dynatrace-oss/dynatrace-managed-mcp-server 1.0.0):

* Every tool REQUIRES an ``environment_alias`` arg (no default). We pass
  ``ALL_ENVIRONMENTS`` so the adapter needs no per-deployment alias config.
* ``list_problems`` returns a HUMAN-READABLE TEXT list (not JSON): lines like
  ``problemId: ...`` / ``  title: ...`` / ``  startTime: 2026-08-04 21:47:03``
  (UTC, space-separated, no zone). It carries NO entity / managementZone.
* ``get_problem_details`` returns ``...json:\n{<full JSON>}`` — the only place
  with affectedEntities, managementZones, entityTags, and rootcause evidence.

So gathering is two-stage: parse the text list to candidates (cheap), then
fetch details JSON for the top-N to get the rich fields cross-granularity
correlation needs (design §4.1 "converge, then deepen"). When a tool is missing
the adapter returns a gap string so the workflow degrades honestly.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ops_pilot.correlation.adapters import (
    ToolRegistry,
    invoke_tool,
    to_epoch_ms,
)
from ops_pilot.correlation.models import StorylineNode
from ops_pilot.correlation.query import StorylineQuery

# Tool-name variants across MCP server versions (dynatrace-managed).
_LIST_PROBLEMS = ("dynatrace_managed_list_problems", "list_problems")
_PROBLEM_DETAILS = ("dynatrace_managed_get_problem_details", "get_problem_details")
_LIST_EVENTS = ("dynatrace_managed_list_events", "list_events")

# This MCP server requires an environment_alias on every call; ALL_ENVIRONMENTS
# queries every configured environment, so we need no per-deployment alias.
_ALL_ENVIRONMENTS = "ALL_ENVIRONMENTS"

# Map Dynatrace impactLevel/severity → storyline severity.
_IMPACT_SEVERITY = {
    "ENVIRONMENT": "critical",
    "SERVICES": "error",
    "INFRASTRUCTURE": "warn",
    "APPLICATION": "error",
}
_SEVERITY_MAP = {
    "AVAILABILITY": "critical",
    "ERROR": "error",
    "CUSTOM_ALERT": "warn",
    "PERFORMANCE": "warn",
    "RESOURCE_CONTENTION": "warn",
    "MONITORING_UNAVAILABLE": "info",
}

# Fields captured per problem from the text list (one "problemId:" block each).
_FIELD_RE = re.compile(r"^\s*(problemId|displayId|title|status|severityLevel|impactLevel|startTime|endTime):\s*(.*)$")


def _text_of(raw: Any) -> str:
    """Coerce an MCP tool result (list of content blocks / str) to text."""

    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        for block in raw:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                return block["text"]
            if isinstance(block, str):
                return block
    content = getattr(raw, "content", None)
    if isinstance(content, str):
        return content
    return str(raw)


def _parse_problem_list(text: str) -> list[dict[str, str]]:
    """Parse the human-readable list_problems text into per-problem dicts.

    Each problem starts at a ``problemId:`` line; subsequent indented ``key:
    value`` lines belong to it until the next ``problemId:`` or a blank block.
    """

    problems: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        match = _FIELD_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key == "problemId":
            current = {"problemId": value}
            problems.append(current)
        elif current is not None:
            current[key] = value
    return problems


# Title-substring → causal tier, kept in sync with correlate._CAUSAL_TIERS but
# using only the title (all the cheap text list gives us). Lower = closer to
# root. Used to decide which candidates survive the max_problems cap.
_TITLE_TIERS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (0, ("gc", "oom", "memory", "cpu", "throttl", "saturation", "disk")),
    (1, ("backoff", "crashloop", "hpa", "consumergrouplag", "partitionstuck", "kafka",
          "connection", "probe", "restart", "ratelimit", "pod", "unhealthy")),
    (2, ("failure rate", "error rate", "response time", "latency", "timeout")),
    (3, ("azanomaly", "availability", "environment", "mongodb")),
)


def _candidate_tier(candidate: dict[str, str]) -> int:
    text = str(candidate.get("title", "")).lower()
    for tier, hints in _TITLE_TIERS:
        if any(hint in text for hint in hints):
            return tier
    if (candidate.get("impactLevel") or "").upper() == "ENVIRONMENT":
        return 3
    return 2


def _select_candidates(candidates: list[dict[str, str]], cap: int) -> list[dict[str, str]]:
    """Keep the ``cap`` most root-cause-like candidates, then order by time.

    Prefer lower causal tiers so truncation never discards the originating
    signal; within the kept set, sort chronologically for a readable timeline.
    """

    if len(candidates) <= cap:
        return candidates
    ranked = sorted(candidates, key=lambda c: (_candidate_tier(c), c.get("startTime", "")))
    kept = ranked[:cap]
    return sorted(kept, key=lambda c: c.get("startTime", ""))


def _severity_for(impact_level: str | None, severity_level: str | None) -> str:
    if impact_level:
        mapped = _IMPACT_SEVERITY.get(impact_level.upper())
        if mapped:
            return mapped
    if severity_level:
        return _SEVERITY_MAP.get(severity_level.upper(), "error")
    return "error"


def _detail_entity(detail: dict[str, Any]) -> tuple[str | None, str | None]:
    """First affected entity (id, name) from a problem-details JSON dict."""

    for key in ("affectedEntities", "impactedEntities"):
        entities = detail.get(key)
        if isinstance(entities, list) and entities:
            first = entities[0]
            if isinstance(first, dict):
                ent = first.get("entityId")
                ent_id = ent.get("id") if isinstance(ent, dict) else (ent if isinstance(ent, str) else None)
                return ent_id, first.get("name")
    return None, None


def _detail_zones(detail: dict[str, Any]) -> list[str]:
    zones: list[str] = []
    for zone in detail.get("managementZones") or []:
        if isinstance(zone, dict) and zone.get("name"):
            zones.append(str(zone["name"]))
    return zones


def _detail_tags(detail: dict[str, Any]) -> list[str]:
    """Flatten entityTags to ``key:value`` (or ``key``) strings for matching."""

    tags: list[str] = []
    for tag in detail.get("entityTags") or []:
        if not isinstance(tag, dict):
            continue
        rep = tag.get("stringRepresentation")
        if rep:
            tags.append(str(rep))
        elif tag.get("key"):
            value = tag.get("value")
            tags.append(f"{tag['key']}:{value}" if value else str(tag["key"]))
    return tags


def _detail_rootcause(detail: dict[str, Any]) -> tuple[bool, str | None]:
    """Extract is_rootcause_relevant + human description from evidenceDetails."""

    evidence = detail.get("evidenceDetails") or {}
    for item in evidence.get("details") or []:
        data = item.get("data") if isinstance(item, dict) else None
        props = data.get("properties") if isinstance(data, dict) else None
        if not isinstance(props, list):
            continue
        prop_map = {p.get("key"): p.get("value") for p in props if isinstance(p, dict)}
        rootcause = str(prop_map.get("dt.event.is_rootcause_relevant", "")).lower() == "true"
        description = prop_map.get("dt.event.description")
        return rootcause, description
    return False, None


def _problem_node_from_detail(candidate: dict[str, str], detail: dict[str, Any]) -> StorylineNode | None:
    """Build a rich problem node from list candidate + details JSON."""

    ts = to_epoch_ms(detail.get("startTime")) or to_epoch_ms(candidate.get("startTime"))
    if ts is None:
        return None
    entity_id, entity_name = _detail_entity(detail)
    zones = _detail_zones(detail)
    tags = _detail_tags(detail)
    rootcause, description = _detail_rootcause(detail)
    title = str(detail.get("title") or candidate.get("title") or "Dynatrace problem")
    return StorylineNode(
        ts=ts,
        source="dynatrace_problem",
        kind=title,
        title=title,
        entity_id=entity_id,
        entity_name=entity_name,
        severity=_severity_for(detail.get("impactLevel"), detail.get("severityLevel")),
        role="context",
        evidence={
            "problemId": detail.get("problemId") or candidate.get("problemId"),
            "displayId": detail.get("displayId") or candidate.get("displayId"),
            "impactLevel": detail.get("impactLevel") or candidate.get("impactLevel"),
            "managementZones": zones,
            "entityTags": tags,
            "is_rootcause_relevant": rootcause,
            "description": description,
        },
    )


def _problem_node_from_candidate(candidate: dict[str, str]) -> StorylineNode | None:
    """Fallback node from the text list alone (no entity/zone available)."""

    ts = to_epoch_ms(candidate.get("startTime"))
    if ts is None:
        return None
    title = candidate.get("title") or "Dynatrace problem"
    return StorylineNode(
        ts=ts,
        source="dynatrace_problem",
        kind=title,
        title=title,
        severity=_severity_for(candidate.get("impactLevel"), candidate.get("severityLevel")),
        role="context",
        evidence={
            "problemId": candidate.get("problemId"),
            "displayId": candidate.get("displayId"),
            "impactLevel": candidate.get("impactLevel"),
        },
    )


async def gather_dynatrace_nodes(
    registry: ToolRegistry,
    query: StorylineQuery,
) -> tuple[list[StorylineNode], list[str]]:
    """Pull Dynatrace problems (with details) into nodes. Returns (nodes, gaps)."""

    nodes: list[StorylineNode] = []
    gaps: list[str] = []

    problems_tool = registry.first(*_LIST_PROBLEMS)
    if problems_tool is None:
        return [], ["Dynatrace problems unavailable (list_problems tool not loaded)."]

    # Stage 1: list problems in the window (text format). No entity lock — mode
    # C pulls everything in the window; entity/zone filtering happens by scoring
    # downstream, because infra-level problems rarely carry the service entity.
    list_args: dict[str, Any] = {
        "from": query.time_from,
        "to": query.time_to,
        "environment_alias": _ALL_ENVIRONMENTS,
        # Earliest first: a fault cascade's root (e.g. the originating GC) starts
        # before its consequences (kafka lag, AZ anomaly). Sorting ascending and
        # capping at max_problems keeps the root rather than truncating it away
        # behind a flood of later, more numerous downstream problems.
        "sort": "+startTime",
    }
    mz = _mz_selector(query)
    if mz:
        list_args["mzSelector"] = mz
    if query.entity_ids:
        list_args["entitySelector"] = _entity_selector(query)

    list_text = _text_of(await invoke_tool(problems_tool, list_args))
    candidates = _parse_problem_list(list_text)
    if not candidates:
        return [], ["No Dynatrace problems in window."]

    # Select which candidates survive the max_problems cap by CAUSAL TIER, not
    # list order. Time-based truncation (asc or desc) can drop the originating
    # tier-0 signal (e.g. the GC) behind more-numerous downstream problems
    # (kafka lag, mongo alerts). Keep the most root-cause-like first, then order
    # the survivors by time for a readable timeline. (Correlate re-tiers on the
    # full node — this is only about not discarding the root before it is seen.)
    candidates = _select_candidates(candidates, query.max_problems)

    # Stage 2: fetch details JSON for the survivors to get entity,
    # managementZones, entityTags, and rootcause evidence. This is what makes
    # cross-granularity correlation possible.
    details_tool = registry.first(*_PROBLEM_DETAILS)
    for candidate in candidates:
        node: StorylineNode | None = None
        if details_tool is not None and candidate.get("problemId"):
            try:
                detail = _fetch_detail(await invoke_tool(
                    details_tool,
                    {"problemId": candidate["problemId"], "environment_alias": _ALL_ENVIRONMENTS},
                ))
            except Exception:  # noqa: BLE001 - details failure falls back to candidate.
                detail = None
            if detail is not None:
                node = _problem_node_from_detail(candidate, detail)
        if node is None:
            node = _problem_node_from_candidate(candidate)
        if node is not None:
            nodes.append(node)

    if details_tool is None:
        gaps.append("Dynatrace problem details unavailable; entity/zone correlation limited.")

    return nodes, gaps


def _fetch_detail(raw: Any) -> dict[str, Any] | None:
    """Extract the JSON body from get_problem_details text: '...json:\\n{...}'."""

    text = _text_of(raw)
    idx = text.find("{")
    end = text.rfind("}")
    if idx == -1 or end == -1 or end <= idx:
        return None
    try:
        parsed = json.loads(text[idx : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _entity_selector(query: StorylineQuery) -> str | None:
    if query.entity_ids:
        ids = ",".join(f'"{eid}"' for eid in query.entity_ids)
        return f"entityId({ids})"
    return None


def _mz_selector(query: StorylineQuery) -> str | None:
    if query.management_zones:
        names = ",".join(f'"{mz}"' for mz in query.management_zones)
        return f"mzName({names})"
    return None
