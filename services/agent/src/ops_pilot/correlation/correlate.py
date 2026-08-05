"""Phase three: correlate — deterministic scoring + role assignment, no LLM.

Assigns each node a causal ``role`` (trigger / propagation / symptom / context)
using explainable rules over real Dynatrace/Kibana signals (design §4.3). No
LLM here — reproducibility and auditability are the whole point. The LLM only
narrates (phase four) over the roles this phase assigns.

Two capabilities matter for real cascades (design §8/§9):

* **Causal tiers** — signals are ranked by where they sit in a fault cascade
  (resource exhaustion → infra propagation → service errors → env symptom), so
  the trigger is chosen by causal position, not just "earliest" or whatever
  Dynatrace flagged rootcause-relevant (which, for the real GC→kafka-lag
  cascade, mislabels the late kafka lag as root).
* **Cross-granularity linking** — a Dynatrace problem sits on an infra/host
  entity while a Kibana 5xx log sits on a service pod; they rarely share an
  entityId. They are linked instead by the problem description naming the
  service, shared management zone, or shared namespace tag — recorded on each
  node's evidence so the narrative can explain the link.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from ops_pilot.correlation.models import StorylineNode

_SEVERITY_RANK = {"critical": 3, "error": 2, "warn": 1, "info": 0}

# Canonical fault-cascade tiers. Lower tier = closer to the root cause. Each
# entry matches a signal by substring against "<kind> <title>". Order matters:
# the first matching tier wins, so put the most root-cause-like hints first.
_CAUSAL_TIERS: tuple[tuple[int, tuple[str, ...]], ...] = (
    # Tier 0 — resource exhaustion / the usual root cause.
    (0, ("gc", "oom", "outofmemory", "memory", "cpu", "saturation", "disk", "throttl")),
    # Tier 1 — infrastructure propagation.
    (1, ("backoff", "crashloop", "hpa", "consumergrouplag", "partitionstuck", "kafka",
         "connection", "probe", "restart", "ratelimit", "pool")),
    # Tier 2 — service-level errors (Dynatrace failure/latency + Kibana 5xx).
    (2, ("failure rate", "error rate", "response time", "latency", "timeout",
         "log.5", "log.6", "5xx")),
    # Tier 3 — environment-wide symptom.
    (3, ("azanomaly", "availability", "environment")),
)

_SYMPTOM_TIER = 3
_DEFAULT_TIER = 2  # Unclassified errors read as service-level propagation.


def _severity_rank(node: StorylineNode) -> int:
    return _SEVERITY_RANK.get(node.severity, 0)


def _haystack(node: StorylineNode) -> str:
    return f"{node.kind} {node.title}".lower()


def _causal_tier(node: StorylineNode) -> int:
    text = _haystack(node)
    for tier, hints in _CAUSAL_TIERS:
        if any(hint in text for hint in hints):
            return tier
    # ENVIRONMENT impact with no keyword still reads as a symptom.
    if node.evidence.get("impactLevel") == "ENVIRONMENT":
        return _SYMPTOM_TIER
    return _DEFAULT_TIER


def _pick_trigger(nodes: list[StorylineNode], tiers: dict[int, int]) -> StorylineNode | None:
    """Choose the root-cause node by causal position, then time.

    ``tiers`` maps id(node) → causal tier. The trigger is the earliest node in
    the lowest tier actually present. Dynatrace's own ``is_rootcause_relevant``
    only breaks ties *within* that tier — it does not override causal position,
    because Dynatrace flags multiple problems in a cascade as rootcause-relevant
    (e.g. it flags the late kafka lag, not the originating GC).
    """

    if not nodes:
        return None
    lowest = min(tiers[id(n)] for n in nodes)
    candidates = [n for n in nodes if tiers[id(n)] == lowest]
    return min(candidates, key=lambda n: (not n.evidence.get("is_rootcause_relevant"), n.ts))


def _assign_role(node: StorylineNode, tier: int, trigger: StorylineNode | None) -> str:
    if trigger is not None and node is trigger:
        return "trigger"
    if tier >= _SYMPTOM_TIER or node.evidence.get("impactLevel") == "ENVIRONMENT":
        return "symptom"
    if _severity_rank(node) >= _SEVERITY_RANK["warn"]:
        return "propagation"
    return "context"


# ---- cross-granularity linking --------------------------------------------

# A service token looks like "lead-service" / "elsa-web-read"; used to detect a
# problem description or entity naming the service a log belongs to.
_SERVICE_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")


def _service_tokens(node: StorylineNode) -> set[str]:
    tokens: set[str] = set()
    if node.entity_name:
        tokens.update(_SERVICE_TOKEN_RE.findall(node.entity_name.lower()))
    return tokens


def _problem_text(node: StorylineNode) -> str:
    parts = [node.title, str(node.evidence.get("description") or "")]
    tags = node.evidence.get("entityTags")
    if isinstance(tags, list):
        parts.extend(str(t) for t in tags)
    if node.entity_name:
        parts.append(node.entity_name)
    return " ".join(parts).lower()


def _zones(node: StorylineNode) -> set[str]:
    zones = node.evidence.get("managementZones")
    return {str(z).lower() for z in zones} if isinstance(zones, list) else set()


def _link_log_to_problems(log: StorylineNode, problems: list[StorylineNode]) -> dict[str, Any] | None:
    """Find the strongest cross-granularity link from a log to a problem.

    Returns a link annotation (reason + target) or None. Strength order:
    1. a problem's text (description/tags/entity) names the log's service,
    2. shared management zone,
    3. shared namespace tag.
    """

    log_tokens = _service_tokens(log)
    log_zones = _zones(log)
    best: dict[str, Any] | None = None
    for problem in problems:
        pid = problem.evidence.get("displayId") or problem.evidence.get("problemId")
        text = _problem_text(problem)
        if log_tokens and any(tok in text for tok in log_tokens):
            return {"reason": "service-named-in-problem", "problem": pid, "strength": "strong"}
        if log_zones and (log_zones & _zones(problem)):
            best = best or {"reason": "shared-management-zone", "problem": pid, "strength": "medium"}
    return best


def correlate_scores(state: dict[str, Any]) -> dict[str, Any]:
    """Assign causal roles over the aligned timeline; identify the trigger."""

    nodes = state.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return {"scored": [], "root_cause": None}

    typed_nodes = [n for n in nodes if isinstance(n, StorylineNode)]
    if not typed_nodes:
        return {"scored": [], "root_cause": None}

    tiers = {id(n): _causal_tier(n) for n in typed_nodes}
    trigger = _pick_trigger(typed_nodes, tiers)

    problems = [n for n in typed_nodes if n.source == "dynatrace_problem"]
    logs = [n for n in typed_nodes if n.source == "kibana_log"]

    scored: list[StorylineNode] = []
    root_cause: StorylineNode | None = None
    for node in typed_nodes:
        role = _assign_role(node, tiers[id(node)], trigger)
        evidence = dict(node.evidence)
        evidence["causal_tier"] = tiers[id(node)]
        # Annotate cross-source links so the narrative can explain them.
        if node.source == "kibana_log" and problems:
            link = _link_log_to_problems(node, problems)
            if link is not None:
                evidence["linked_to"] = link
        elif node is trigger and node.source == "dynatrace_problem" and logs:
            linked = [
                lg.entity_name
                for lg in logs
                if (lnk := _link_log_to_problems(lg, [node])) is not None and lnk["strength"] == "strong"
            ]
            if linked:
                evidence["impacts_services"] = sorted(set(filter(None, linked)))
        updated = replace(node, role=role, evidence=evidence)
        scored.append(updated)
        if trigger is not None and node is trigger:
            root_cause = updated

    return {"scored": scored, "root_cause": root_cause}
