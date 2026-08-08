"""Unit tests for the deterministic correlation phases and full pipeline.

The scoring and alignment phases are pure and deterministic by design (no LLM),
so they are exercised directly. The full pipeline is run with fake MCP tools
returning real-shaped Dynatrace/Kibana payloads and a fake model.
"""

from __future__ import annotations

import json

import pytest

from ops_pilot.correlation.adapters import ToolRegistry, invoke_tool, to_epoch_ms
from ops_pilot.correlation.adapters.kibana import _extract_hits, _log_node, _unwrap_api_response
from ops_pilot.correlation.align import align_nodes
from ops_pilot.correlation.correlate import correlate_scores
from ops_pilot.correlation.models import StorylineNode
from ops_pilot.correlation.orchestrator import build_storyline_tool, run_storyline
from ops_pilot.correlation.query import normalize_query


class _FakeTool:
    def __init__(self, name: str, payload: object) -> None:
        self.name = name
        self._payload = payload
        self.calls: list[dict] = []

    async def ainvoke(self, args: dict) -> object:
        self.calls.append(args)
        return self._payload


class _FakeModel:
    def __init__(self, content: str = '{"narrative": "GC caused 503s", "confidence": 0.8}') -> None:
        self._content = content

    async def ainvoke(self, messages: list) -> object:
        class _Resp:
            content = self._content

        return _Resp()


def _node(
    ts: int,
    *,
    source: str = "dynatrace_problem",
    kind: str = "X",
    severity: str = "info",
    **kw,
) -> StorylineNode:
    return StorylineNode(ts=ts, source=source, kind=kind, title=kind, severity=severity, **kw)


# ---- to_epoch_ms -----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1785848524236, 1785848524236),  # already ms
        (1785848524, 1785848524000),  # seconds → ms
        ("2026-08-05T02:09:52.023Z", 1785895792023),  # ISO8601 UTC
        (None, None),
        ("not-a-date", None),
    ],
)
def test_to_epoch_ms_normalizes(value, expected):
    assert to_epoch_ms(value) == expected


# ---- query normalization ---------------------------------------------------


def test_normalize_query_infers_mode():
    assert normalize_query({"seed_problem_id": "P-1"}).mode == "B"
    assert normalize_query({"service_names": ["event-consumer"]}).mode == "A"
    assert normalize_query({}).mode == "C"


def test_normalize_query_coerces_scalars_to_tuples():
    query = normalize_query({"service_names": "event-consumer", "entity_ids": ["A", "B"]})
    assert query.service_names == ("event-consumer",)
    assert query.entity_ids == ("A", "B")


# ---- align (phase two) -----------------------------------------------------


def test_align_merges_and_sorts_by_time():
    state = {
        "raw_dynatrace": [_node(300), _node(100)],
        "raw_kibana": [_node(200, source="kibana_log")],
        "gaps_dt": ["dt gap"],
        "gaps_kb": ["kb gap"],
    }
    out = align_nodes(state)
    assert [n.ts for n in out["nodes"]] == [100, 200, 300]
    assert out["gaps"] == ["dt gap", "kb gap"]


def test_align_handles_empty_sources():
    out = align_nodes({})
    assert out["nodes"] == []
    assert out["gaps"] == []


# ---- correlate (phase three) -----------------------------------------------


def test_correlate_picks_earliest_gc_like_as_trigger():
    nodes = [
        _node(100, kind="LongJAVAGCTime", severity="critical"),
        _node(200, source="kibana_log", kind="log.503", severity="error"),
    ]
    out = correlate_scores({"nodes": nodes})
    root = out["root_cause"]
    assert root is not None
    assert root.kind == "LongJAVAGCTime"
    assert root.role == "trigger"
    # The later 503 is propagation, not trigger.
    later = [n for n in out["scored"] if n.kind == "log.503"][0]
    assert later.role == "propagation"


def test_correlate_marks_environment_impact_as_symptom():
    nodes = [
        _node(100, kind="LongJAVAGCTime", severity="critical"),
        _node(300, kind="AZAnomalyIdentified", severity="critical", evidence={"impactLevel": "ENVIRONMENT"}),
    ]
    out = correlate_scores({"nodes": nodes})
    symptom = [n for n in out["scored"] if n.kind == "AZAnomalyIdentified"][0]
    assert symptom.role == "symptom"


def test_correlate_prefers_rootcause_flagged():
    nodes = [
        _node(100, kind="SomethingEarly", severity="warn"),
        _node(50, kind="FlaggedCause", severity="error", evidence={"is_rootcause_relevant": True}),
    ]
    out = correlate_scores({"nodes": nodes})
    assert out["root_cause"].kind == "FlaggedCause"


def test_correlate_empty_timeline():
    out = correlate_scores({"nodes": []})
    assert out["scored"] == []
    assert out["root_cause"] is None


# ---- tool registry ---------------------------------------------------------


def test_tool_registry_first_returns_available_variant():
    tool = _FakeTool("list_problems", {})
    registry = ToolRegistry([tool])
    assert registry.first("dynatrace_managed_list_problems", "list_problems") is tool
    assert registry.first("nonexistent") is None


@pytest.mark.asyncio
async def test_invoke_tool_uses_tool_call_envelope_for_toolmessage_output():
    from langchain_core.messages import ToolMessage
    from langchain_core.tools import tool

    @tool
    async def content_blocks(query: str) -> list[dict[str, str]]:
        """Return MCP-style content blocks."""

        return [{"type": "text", "text": f"result: {query}"}]

    result = await invoke_tool(content_blocks, {"query": "x"})

    assert isinstance(result, ToolMessage)
    assert result.tool_call_id.startswith("storyline-content_blocks-")
    assert result.content == [{"type": "text", "text": "result: x"}]


# ---- full pipeline ---------------------------------------------------------


@pytest.mark.asyncio
async def test_run_storyline_end_to_end_with_fake_tools():
    # Real dynatrace-managed contract: list_problems returns a HUMAN-READABLE
    # TEXT list, and get_problem_details returns "...json:\n{<full JSON>}".
    problem_list_text = (
        "Listing 1 of 1 problems from environment frankfurt.\n\n"
        "problemId: 7370551928022586600_1785848520000V2\n"
        "  displayId: P-26081079\n"
        "  title: LongJAVAGCTime\n"
        "  status: CLOSED\n"
        "  severityLevel: CUSTOM_ALERT\n"
        "  impactLevel: INFRASTRUCTURE\n"
        "  startTime: 2026-08-05 01:47:00\n"
        "  endTime: 2026-08-05 02:07:00\n\n"
    )
    problem_detail_json = {
        "problemId": "7370551928022586600_1785848520000V2",
        "displayId": "P-26081079",
        "title": "LongJAVAGCTime",
        "impactLevel": "INFRASTRUCTURE",
        "severityLevel": "CUSTOM_ALERT",
        "startTime": 1785848820000,
        "affectedEntities": [
            {"entityId": {"id": "CLOUD_APPLICATION-9357", "type": "CLOUD_APPLICATION"}, "name": "event-consumer"}
        ],
        "managementZones": [{"id": "1", "name": "Event Service and Consumer"}],
        "entityTags": [{"context": "CONTEXTLESS", "key": "critical-component", "value": "event",
                        "stringRepresentation": "critical-component:event"}],
        "evidenceDetails": {
            "details": [
                {"data": {"properties": [
                    {"key": "dt.event.is_rootcause_relevant", "value": "true"},
                    {"key": "dt.event.description", "value": "Pod event-consumer had GC events exceeding 300ms"},
                ]}}
            ]
        },
    }
    detail_text = (
        "Details of problem from environment frankfurt in the following json:\n" + json.dumps(problem_detail_json)
    )

    istio_payload = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "@timestamp": "2026-08-05T01:48:25.000Z",
                        "trace.id": "e98ddcdf2fe934599f100a1abefd1335",
                        "response_code": 503,
                        "response_flags": "URX,UF",
                        "authority": "event-consumer:8080",
                        "method": "POST",
                        "path": "/event-consumer/refresh",
                        "kubernetes.labels.app": "event-consumer",
                        "kubernetes.pod.name": "event-consumer-56",
                    }
                },
                {
                    "_source": {
                        "@timestamp": "2026-08-05T01:48:00.000Z",
                        "authority": "169.254.169.254",
                        "response_code": 401,
                    }
                },
            ]
        }
    }
    kibana_response = [{"type": "text", "text": f"[Space: test] API response: {json.dumps(istio_payload)}"}]

    tools = [
        _FakeTool("dynatrace_managed_list_problems", [{"type": "text", "text": problem_list_text}]),
        _FakeTool("dynatrace_managed_get_problem_details", [{"type": "text", "text": detail_text}]),
        _FakeTool("execute_kb_api", kibana_response),
    ]

    out = await run_storyline(
        {"service_names": ["event-consumer"], "time_from": "now-1h"},
        tools=tools,
        model=_FakeModel(),
    )

    assert out["status"] == "ready"
    # GC problem + one 503 log survive; the metadata-probe noise is converged out.
    kinds = {node["kind"] for node in out["nodes"]}
    assert "LongJAVAGCTime" in kinds
    assert "log.503" in kinds
    # The GC problem (causal tier 0) wins as trigger over the tier-2 503 log.
    assert out["root_cause"]["kind"] == "LongJAVAGCTime"
    assert out["root_cause"]["role"] == "trigger"
    # Cross-granularity link: the 503 log (service pod) links to the GC problem
    # (CLOUD_APPLICATION entity) because the problem description names the service.
    log_node = next(n for n in out["nodes"] if n["kind"] == "log.503")
    assert log_node["evidence"]["linked_to"]["strength"] == "strong"
    assert out["narrative"] == "GC caused 503s"
    assert out["confidence"] == 0.8
    # Noise convergence recorded as a gap.
    assert any("noise" in gap for gap in out["gaps"])


@pytest.mark.asyncio
async def test_run_storyline_degrades_to_gaps_without_tools():
    out = await run_storyline({"service_names": ["svc"]}, tools=[], model=_FakeModel())
    assert out["status"] == "ready"
    assert out["nodes"] == []
    assert len(out["gaps"]) >= 1


@pytest.mark.asyncio
async def test_build_storyline_tool_writes_state_command():
    """The deep-agent tool returns a Command that writes the storyline state key."""

    storyline_tool = build_storyline_tool(tools=[], model=_FakeModel())
    command = await storyline_tool.ainvoke(
        {
            "args": {"service_names": ["event-consumer"]},
            "id": "call-1",
            "name": "build_storyline",
            "type": "tool_call",
        }
    )
    # Command.update carries both the storyline state key and a tool message.
    update = command.update
    assert "storyline" in update
    assert update["storyline"]["status"] in {"ready", "error"}
    assert update["messages"], "tool message summary must be present"



def test_kibana_adapter_parses_real_execute_kb_api_shape():
    """Regression: real execute_kb_api output — text-prefixed wrapper, nested
    kubernetes object, flat trace.id key (captured from a live proxy call)."""

    real_response = {
        "content": [
            {
                "type": "text",
                "text": (
                    "[Space: cxm-sales-and-service-cloud-monitoring] API response: "
                    + json.dumps(
                        {
                            "hits": {
                                "hits": [
                                    {
                                        "_source": {
                                            "@timestamp": "2026-08-05T06:13:37.263Z",
                                            "kubernetes": {
                                                "labels": {"app": "iam-new-service"},
                                                "pod": {"name": "iam-new-service-59f7c6965d-ng8hs"},
                                            },
                                            "authority": "iam-new-service-svc:50051",
                                            "response_flags": "-",
                                            "path": "/com.sap.crm.iamserviceproto.IamService/GetAccessRestrictions",
                                            "trace.id": "93bc29ebf0782dedaa840e9a17ad89f6",
                                            "response_code": 200,
                                            "method": "POST",
                                        }
                                    }
                                ]
                            }
                        }
                    )
                ),
            }
        ]
    }

    hits = _extract_hits(_unwrap_api_response(real_response))
    assert len(hits) == 1
    node = _log_node(hits[0])
    assert node is not None
    # Nested kubernetes.labels.app resolves via the _nested fallback.
    assert node.entity_name == "iam-new-service"
    # Flat dotted key resolves directly.
    assert node.evidence["trace.id"] == "93bc29ebf0782dedaa840e9a17ad89f6"
    assert node.evidence["pod"] == "iam-new-service-59f7c6965d-ng8hs"
    assert node.severity == "info"  # 200 → info


def test_kibana_adapter_parses_top_level_list_shape():
    """Regression: langchain-mcp-adapters returns the content blocks as a
    TOP-LEVEL list (not wrapped in {"content": [...]}). This shape produced
    0 nodes + a false 'no logs' gap in production despite data existing."""

    istio = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "@timestamp": "2026-08-05T07:00:07.628Z",
                        "kubernetes": {"labels": {"app": "event-consumer"}, "pod": {"name": "event-consumer-122"}},
                        "authority": "change-history-svc:50051",
                        "response_flags": "-",
                        "path": "/com.sap.crm.eventserviceproto.EventService/notify",
                        "trace.id": "f457fabbabceff71bd459cc8c33109ff",
                        "response_code": 200,
                        "method": "POST",
                    }
                }
            ]
        }
    }
    top_level_list = [{"type": "text", "text": f"[Space: cxm] API response: {json.dumps(istio)}"}]

    hits = _extract_hits(_unwrap_api_response(top_level_list))
    assert len(hits) == 1
    node = _log_node(hits[0])
    assert node is not None
    assert node.entity_name == "event-consumer"
    assert node.evidence["trace.id"] == "f457fabbabceff71bd459cc8c33109ff"


def test_kibana_adapter_raises_on_token_limit():
    """Regression: the MCP server returns a 'Token limit exceeded' text (not an
    ES body) when the response is too large. This must surface as an explicit
    error → precise gap, not a silent empty '{}' that reads as 'no logs'."""

    from ops_pilot.correlation.adapters.kibana import KibanaTokenLimitError, _unwrap_api_response

    token_limit = [
        {"type": "text", "text": "Token limit exceeded: result contains 26516 tokens (limit: 20000).\n\nSuggestions:"}
    ]
    with pytest.raises(KibanaTokenLimitError):
        _unwrap_api_response(token_limit)


# ---- causal-tier correlation (cross-granularity) ---------------------------


def test_correlate_causal_tier_beats_dynatrace_rootcause_flag():
    """The real GC→kafka-lag cascade: Dynatrace flags the LATE kafka lag as
    rootcause-relevant, but the earlier GC (causal tier 0) is the true root.
    Causal position must win over the rootcause flag."""

    nodes = [
        _node(1000, kind="LongJAVAGCTime", severity="warn", evidence={"is_rootcause_relevant": False}),
        _node(2000, kind="LargeConsumerGroupLag", severity="warn", evidence={"is_rootcause_relevant": True}),
    ]
    out = correlate_scores({"nodes": nodes})
    assert out["root_cause"].kind == "LongJAVAGCTime"
    assert out["root_cause"].role == "trigger"
    # The kafka lag is tier-1 propagation, not the root.
    lag = next(n for n in out["scored"] if n.kind == "LargeConsumerGroupLag")
    assert lag.role == "propagation"


def test_correlate_full_cascade_roles():
    """GC (trigger) → failure-rate + 5xx (propagation) → AZ anomaly (symptom)."""

    nodes = [
        _node(1000, kind="LongJAVAGCTime", severity="warn"),
        _node(2000, kind="Failure rate increase", severity="error"),
        _node(3000, source="kibana_log", kind="log.503", severity="error"),
        _node(4000, kind="AZAnomalyIdentified", severity="critical", evidence={"impactLevel": "ENVIRONMENT"}),
    ]
    out = correlate_scores({"nodes": nodes})
    roles = {n.kind: n.role for n in out["scored"]}
    assert roles["LongJAVAGCTime"] == "trigger"
    assert roles["Failure rate increase"] == "propagation"
    assert roles["log.503"] == "propagation"
    assert roles["AZAnomalyIdentified"] == "symptom"


def test_correlate_cross_granularity_link_by_service_name():
    """A 503 log on a service pod links to an infra GC problem whose description
    names that service — WITHOUT any shared entityId."""

    problem = _node(
        1000, kind="LongJAVAGCTime", severity="warn", entity_name="campaign-service",
        evidence={"description": "Pod lead-service-abc had GC events exceeding 300ms", "displayId": "P-1"},
    )
    log = _node(2000, source="kibana_log", kind="log.503", severity="error", entity_name="lead-service")
    out = correlate_scores({"nodes": [problem, log]})
    log_scored = next(n for n in out["scored"] if n.source == "kibana_log")
    assert log_scored.evidence["linked_to"]["reason"] == "service-named-in-problem"
    assert log_scored.evidence["linked_to"]["problem"] == "P-1"


def test_correlate_cross_granularity_link_by_management_zone():
    problem = _node(
        1000, kind="Failure rate increase", severity="error", entity_name="elsa-web-read",
        evidence={"managementZones": ["ELSA"], "displayId": "P-2"},
    )
    log = _node(2000, source="kibana_log", kind="log.503", severity="error", entity_name="some-other-svc",
                evidence={"managementZones": ["ELSA"]})
    out = correlate_scores({"nodes": [problem, log]})
    log_scored = next(n for n in out["scored"] if n.source == "kibana_log")
    assert log_scored.evidence["linked_to"]["reason"] == "shared-management-zone"


# ---- dynatrace text-list parser --------------------------------------------


def test_dynatrace_parse_problem_list_text():
    from ops_pilot.correlation.adapters.dynatrace import _parse_problem_list

    text = (
        "Listing 2 of 2 problems from environment frankfurt.\n\n"
        "problemId: ABC_123V2\n"
        "  displayId: P-100\n"
        "  title: LongJAVAGCTime\n"
        "  impactLevel: INFRASTRUCTURE\n"
        "  startTime: 2026-08-04 21:47:03\n\n"
        "problemId: DEF_456V2\n"
        "  displayId: P-101\n"
        "  title: Failure rate increase\n"
        "  impactLevel: SERVICES\n"
        "  startTime: 2026-08-04 21:58:00\n\n"
    )
    problems = _parse_problem_list(text)
    assert len(problems) == 2
    assert problems[0]["problemId"] == "ABC_123V2"
    assert problems[0]["title"] == "LongJAVAGCTime"
    assert problems[1]["displayId"] == "P-101"
    assert problems[1]["impactLevel"] == "SERVICES"


def test_dynatrace_fetch_detail_extracts_json():
    from ops_pilot.correlation.adapters.dynatrace import _fetch_detail

    raw = [{"type": "text", "text": 'Details of problem from environment frankfurt in the following json:\n'
            '{"problemId": "X", "impactLevel": "SERVICES", "managementZones": [{"name": "ELSA"}]}'}]
    detail = _fetch_detail(raw)
    assert detail is not None
    assert detail["problemId"] == "X"
    assert detail["managementZones"][0]["name"] == "ELSA"
