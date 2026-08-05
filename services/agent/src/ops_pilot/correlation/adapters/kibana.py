"""Kibana source adapter — istio/filebeat logs into normalized StorylineNodes.

Wraps the runtime-loaded Kibana MCP tool (an ES ``_search`` proxy). Applies
noise convergence (design §2.4: metadata-service probe noise dominates failed
calls) and normalizes ``@timestamp`` (ISO8601) → epoch ms. Degrades to a gap
when the tool is missing or logs have rolled off (retention mismatch, §8).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ops_pilot.correlation.adapters import (
    ToolRegistry,
    invoke_tool,
    to_epoch_ms,
)
from ops_pilot.correlation.models import StorylineNode
from ops_pilot.correlation.query import StorylineQuery

# The Kibana MCP server (mcp-server-kibana) exposes a generic Kibana API proxy
# rather than a dedicated ES search tool. ES `_search` goes through the Console
# proxy: POST /api/console/proxy?path=<index>/_search. Tool name: execute_kb_api.
_API_TOOL = ("execute_kb_api",)

_ISTIO_INDEX = "com.sap.cxm.istio.mesh.access_logs*"
_PROXY_PATH = "/api/console/proxy"


class KibanaTokenLimitError(RuntimeError):
    """Raised when the Kibana MCP server refuses a response over its token cap."""

# Noise blacklist (design §2.4 / §9): metadata-service probes dominate failures.
_NOISE_AUTHORITIES = {"169.254.169.254", "metadata.google.internal"}


def _is_noise(log: Mapping[str, Any]) -> bool:
    authority = str(log.get("authority") or "")
    return any(marker in authority for marker in _NOISE_AUTHORITIES)


def _severity_for_status(response_code: Any) -> str:
    try:
        code = int(response_code)
    except (TypeError, ValueError):
        return "info"
    if code >= 500:
        return "error"
    if code >= 400:
        return "warn"
    return "info"


def _log_node(log: Mapping[str, Any]) -> StorylineNode | None:
    ts = to_epoch_ms(log.get("@timestamp") or log.get("timestamp"))
    if ts is None:
        return None
    response_code = log.get("response_code")
    response_flags = log.get("response_flags")
    app = log.get("kubernetes.labels.app") or _nested(log, "kubernetes", "labels", "app")
    pod = log.get("kubernetes.pod.name") or _nested(log, "kubernetes", "pod", "name")
    path = log.get("path")
    title = f"{log.get('method', '')} {path or ''} → {response_code}".strip()
    return StorylineNode(
        ts=ts,
        source="kibana_log",
        kind=f"log.{response_code}" if response_code else "log",
        title=title or "Kibana log",
        entity_id=None,
        entity_name=str(app) if app else None,
        severity=_severity_for_status(response_code),
        role="context",
        evidence={
            "trace.id": log.get("trace.id") or _nested(log, "trace", "id"),
            "response_flags": response_flags,
            "authority": log.get("authority"),
            "upstream_cluster": log.get("upstream_cluster"),
            "pod": pod,
        },
    )


def _nested(source: Mapping[str, Any], *keys: str) -> Any:
    current: Any = source
    for key in keys:
        if isinstance(current, Mapping):
            current = current.get(key)
        else:
            return None
    return current


def _build_query_body(query: StorylineQuery) -> dict[str, Any]:
    filters: list[dict[str, Any]] = [
        {"range": {"@timestamp": {"gte": query.time_from, "lte": query.time_to}}},
    ]
    if query.service_names:
        filters.append({"terms": {"kubernetes.labels.app": list(query.service_names)}})
    return {
        "size": query.max_log_lines,
        # Failures first, then chronological. A busy service emits far more 200s
        # than the limited size budget can hold; sorting by response_code desc
        # ensures 5xx/4xx (the fault signal) surface before the flood of 200s is
        # truncated away. Ties broken by time so the timeline stays readable.
        "sort": [{"response_code": "desc"}, {"@timestamp": "asc"}],
        "query": {"bool": {"filter": filters}},
        "_source": [
            "@timestamp",
            "trace.id",
            "authority",
            "upstream_cluster",
            "response_code",
            "response_flags",
            "method",
            "path",
            "kubernetes.labels.app",
            "kubernetes.pod.name",
        ],
    }


def _extract_hits(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    hits = payload.get("hits")
    if isinstance(hits, Mapping):
        inner = hits.get("hits")
        if isinstance(inner, list):
            return [
                hit.get("_source", hit) if isinstance(hit, Mapping) else hit
                for hit in inner
                if isinstance(hit, Mapping)
            ]
    return []


def _text_from_content_blocks(blocks: list[Any]) -> str | None:
    """Find the first text payload in an MCP content-block list."""

    for block in blocks:
        if isinstance(block, Mapping) and isinstance(block.get("text"), str):
            return block["text"]
        if isinstance(block, str):
            return block
    return None


def _unwrap_api_response(payload: Any) -> Any:
    """Extract the ES JSON body from an execute_kb_api result.

    Handles every shape the tool can arrive in:
      * a top-level list of content blocks — the langchain-mcp-adapters shape,
        e.g. ``[{"type": "text", "text": "[Space: X] API response: <JSON>"}]``
      * a ``{"content": [...]}`` dict wrapping those blocks
      * a bare string (already unwrapped)
      * an already-parsed ES response dict (has ``hits``) — passed through
    Then strips the ``API response:`` label and parses the JSON body.

    Raises ``KibanaTokenLimitError`` when the MCP server refused the response
    for exceeding its token cap, so the caller can report a precise gap instead
    of a misleading "no logs" one.
    """

    text: str | None = None
    if isinstance(payload, list):
        text = _text_from_content_blocks(payload)
    elif isinstance(payload, Mapping):
        content = payload.get("content")
        if isinstance(content, list):
            text = _text_from_content_blocks(content)
        else:
            # Already an ES response dict (e.g. has "hits") — pass through.
            return payload
    elif isinstance(payload, str):
        text = payload

    if text is None:
        return {}

    if "Token limit exceeded" in text:
        raise KibanaTokenLimitError(text.split("\n", 1)[0].strip())

    marker = "API response:"
    idx = text.find(marker)
    body = text[idx + len(marker) :].strip() if idx != -1 else text.strip()
    try:
        return json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return {}


async def gather_kibana_nodes(
    registry: ToolRegistry,
    query: StorylineQuery,
) -> tuple[list[StorylineNode], list[str]]:
    """Pull Kibana istio logs, converge noise, normalize. Returns (nodes, gaps)."""

    if not query.service_names:
        return [], ["Kibana logs skipped (no service_names to filter by)."]

    api_tool = registry.first(*_API_TOOL)
    if api_tool is None:
        return [], ["Kibana logs unavailable (execute_kb_api tool not loaded)."]

    body = _build_query_body(query)
    # ES _search via the Kibana Console proxy: POST /api/console/proxy?path=...
    raw = await invoke_tool(
        api_tool,
        {
            "method": "POST",
            "path": _PROXY_PATH,
            "params": {"path": f"{_ISTIO_INDEX}/_search", "method": "POST"},
            "body": body,
        },
    )
    try:
        payload = _unwrap_api_response(raw)
    except KibanaTokenLimitError as exc:
        return [], [f"Kibana logs truncated by MCP token cap ({exc}); lower max_log_lines."]
    hits = _extract_hits(payload)
    if not hits:
        return [], ["No Kibana logs in window (possible retention mismatch)."]

    nodes: list[StorylineNode] = []
    dropped_noise = 0
    for log in hits:
        if _is_noise(log):
            dropped_noise += 1
            continue
        node = _log_node(log)
        if node is not None:
            nodes.append(node)

    gaps: list[str] = []
    if dropped_noise:
        gaps.append(f"Converged {dropped_noise} metadata-probe noise log(s).")
    return nodes, gaps
