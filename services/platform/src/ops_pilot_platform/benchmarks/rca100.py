"""OpsPilot's isolated RCA100 JSON-over-stdio adapter."""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import pyarrow.compute as arrow_compute
import pyarrow.dataset as arrow_dataset
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import ToolRuntime, tool
from ops_pilot.agent.runtime import build_agent_runtime
from ops_pilot.runtime.spec import RuntimeSpec
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ops_pilot_platform.entrypoints.benchmark import build_rca100_runtime_spec

SRE_SYSTEM_PROMPT = """You are a senior site reliability engineer diagnosing a production incident
from read-only observability data.

Your goals are to identify the earliest credible faulting entity and failure
mechanism, explain how the failure propagated to the reported symptom, and
ground every conclusion in time-aligned evidence.

Use a disciplined troubleshooting method:
1. Establish the incident window, affected entity, and user-visible impact.
2. Compare incident signals with a preceding healthy baseline while preserving
   timestamps and measurement units.
3. Use metrics to establish onset and scope, logs to identify failure details,
   traces and topology to determine dependency direction, and events and alerts
   to identify changes and lifecycle transitions.
4. Form a small set of plausible hypotheses and actively seek both confirming
   and disconfirming evidence.
5. Separate root cause, propagation, and impact. Correlation or temporal
   coincidence alone is not proof of causation.
6. Prefer the simplest explanation that accounts for all strong evidence.
   State uncertainty when evidence is insufficient and never fabricate facts.

Keep the investigation read-only. Use only the supplied incident context and
observation tools. Call one observation tool at a time and pass one scalar value
per argument; make separate calls for separate selectors or time windows. Follow
the requested output schema exactly, without Markdown or additional commentary."""

RCA100Source = Literal["metrics", "logs", "traces", "events", "alerts"]


class RCA100Request(BaseModel):
    """Public request sent by the framework-neutral RCA100 runner."""

    model_config = ConfigDict(extra="forbid")

    benchmark: Literal["rca100"]
    task_id: str
    task: dict[str, Any]
    case_directory: Path
    parquet_schemas: dict[str, list[str]]
    topology_path: Path
    prediction_schema: dict[str, Any]

    @model_validator(mode="after")
    def validate_case_paths(self) -> RCA100Request:
        case_directory = self.case_directory.resolve()
        topology_path = self.topology_path.resolve()
        if topology_path != case_directory / "topology.json":
            raise ValueError("topology_path must point to topology.json inside case_directory.")
        if not case_directory.is_dir() or not topology_path.is_file():
            raise ValueError("RCA100 public case files are unavailable.")
        self.case_directory = case_directory
        self.topology_path = topology_path
        return self


@dataclass(frozen=True)
class RCA100Context:
    """Per-run dependency hidden from the model-visible tool schema."""

    case_directory: Path


class ToolInput(BaseModel):
    """Strict model-generated observation query."""

    model_config = ConfigDict(extra="forbid")


class TimeRangeQuery(ToolInput):
    start_time: str | None = Field(
        default=None,
        description="One ISO-8601 lower-bound timestamp, or null. Never pass a list.",
    )
    end_time: str | None = Field(
        default=None,
        description="One ISO-8601 upper-bound timestamp, or null. Never pass a list.",
    )


class MetricQuery(TimeRangeQuery):
    metric: str | None = Field(default=None, description="One exact metric name, or null. Never pass a list.")
    entity_name: str | None = Field(
        default=None,
        description="One exact entity name, or null. Never pass a list.",
    )
    entity_id: str | None = Field(default=None, description="One exact entity identifier, or null.")
    domain: Literal["apm", "k8s"] | None = Field(default=None, description="One entity domain, or null.")
    entity_set: str | None = Field(default=None, description="One exact entity-set name, or null.")
    limit: int = Field(default=200, ge=1, le=500, description="Maximum samples to return.")


class LogQuery(TimeRangeQuery):
    keyword: str | None = Field(default=None, description="One case-insensitive text fragment, or null.")
    pod_name: str | None = Field(default=None, description="One exact pod name, or null.")
    namespace: str | None = Field(default=None, description="One exact namespace, or null.")
    limit: int = Field(default=100, ge=1, le=300, description="Maximum log records to return.")


class TraceQuery(TimeRangeQuery):
    service_name: str | None = Field(default=None, description="One exact service name, or null.")
    span_name: str | None = Field(default=None, description="One exact span operation name, or null.")
    trace_id: str | None = Field(default=None, description="One exact trace identifier, or null.")
    status_code: str | None = Field(default=None, description="One exact span status code, or null.")
    keyword: str | None = Field(default=None, description="One text fragment for span details, or null.")
    limit: int = Field(default=100, ge=1, le=300, description="Maximum spans to return.")


class EventQuery(ToolInput):
    keyword: str | None = Field(default=None, description="One text fragment for the event body, or null.")
    pod_name: str | None = Field(default=None, description="One exact pod name, or null.")
    level: str | None = Field(default=None, description="One exact event level, or null.")
    limit: int = Field(default=100, ge=1, le=300, description="Maximum events to return.")


class AlertQuery(TimeRangeQuery):
    subject: str | None = Field(default=None, description="One subject text fragment, or null.")
    status: str | None = Field(default=None, description="One exact alert status, or null.")
    limit: int = Field(default=50, ge=1, le=100, description="Maximum alert records to return.")


class TopologyQuery(ToolInput):
    entity_name: str | None = Field(default=None, description="One entity-name fragment, or null.")
    relation: str | None = Field(default=None, description="One exact dependency relation, or null.")
    limit: int = Field(default=200, ge=1, le=500, description="Maximum entities and edges to return.")


class IncidentEvidence(BaseModel):
    """One numeric or directly observable checkpoint supporting a diagnosis."""

    model_config = ConfigDict(extra="forbid")

    source_type: str
    signal: str
    comparator: str
    value: float
    unit: str = ""


class IncidentReasoningStep(BaseModel):
    """One causal step from origin through propagation to impact."""

    model_config = ConfigDict(extra="forbid")

    step_type: Literal["cause", "propagation", "impact"]
    target: str
    fault_type: str
    evidence: list[IncidentEvidence] = Field(default_factory=list)


class IncidentDiagnosis(BaseModel):
    """Structured diagnosis of a production incident."""

    model_config = ConfigDict(extra="forbid")

    root_cause_entities: list[str] = Field(default_factory=list)
    root_cause_types: list[str] = Field(default_factory=list)
    reasoning: list[IncidentReasoningStep] = Field(default_factory=list)


@tool(args_schema=MetricQuery)
def query_metric(
    runtime: ToolRuntime[RCA100Context],
    metric: str | None = None,
    entity_name: str | None = None,
    entity_id: str | None = None,
    domain: Literal["apm", "k8s"] | None = None,
    entity_set: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: Annotated[int, Field(ge=1, le=500)] = 200,
) -> str:
    """Query metric samples from the incident observability store.

    Times are ISO-8601 values. Call without selectors to list the available
    metrics and entities, then narrow by metric/entity and compare the alert
    window with an earlier baseline.
    """

    dataset = _dataset(runtime, "metrics")
    if all(value is None for value in (metric, entity_name, entity_id, domain, entity_set, start_time, end_time)):
        catalog = dataset.to_table(columns=["domain", "entity_set", "entity_name", "metric"])
        return _json(
            {
                "source": "metrics",
                "metrics": sorted(value for value in set(catalog["metric"].to_pylist()) if value),
                "entities": sorted(value for value in set(catalog["entity_name"].to_pylist()) if value)[:500],
                "entity_sets": sorted(value for value in set(catalog["entity_set"].to_pylist()) if value),
            }
        )

    expression = _and(
        _equals("metric", metric),
        _equals("entity_name", entity_name),
        _equals("entity_id", entity_id),
        _equals("domain", domain),
        _equals("entity_set", entity_set),
        _lower_bound("time", _epoch(start_time, unit="us")),
        _upper_bound("time", _epoch(end_time, unit="us")),
    )
    rows = _scan_rows(
        dataset,
        columns=["time", "domain", "entity_set", "entity_id", "entity_name", "metric", "value", "service"],
        expression=expression,
        limit=limit,
    )
    return _rows("metrics", rows)


@tool(args_schema=LogQuery)
def query_logs(
    runtime: ToolRuntime[RCA100Context],
    keyword: str | None = None,
    pod_name: str | None = None,
    namespace: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: Annotated[int, Field(ge=1, le=300)] = 100,
) -> str:
    """Query application logs by time, pod, namespace, and keyword."""

    dataset = _dataset(runtime, "logs")
    expression = _and(
        _equals("_pod_name_", pod_name),
        _equals("_namespace_", namespace),
        _lower_bound("_time_", start_time),
        _upper_bound("_time_", end_time),
    )
    rows = _scan_rows(
        dataset,
        columns=["_time_", "_namespace_", "_pod_name_", "_container_name_", "content"],
        expression=expression,
        contains=(("content", keyword),),
        limit=limit,
    )
    return _rows("logs", rows)


@tool(args_schema=TraceQuery)
def query_traces(
    runtime: ToolRuntime[RCA100Context],
    service_name: str | None = None,
    span_name: str | None = None,
    trace_id: str | None = None,
    status_code: str | None = None,
    keyword: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: Annotated[int, Field(ge=1, le=300)] = 100,
) -> str:
    """Query trace spans by service, operation, trace, status, time, or text.

    The keyword searches status messages, attributes, and span events. Times
    are ISO-8601 values converted to the dataset's nanosecond timestamps.
    """

    dataset = _dataset(runtime, "traces")
    expression = _and(
        _equals("serviceName", service_name),
        _equals("spanName", span_name),
        _equals("traceId", trace_id),
        _equals("statusCode", status_code),
        _lower_bound("startTime", _epoch_text(start_time, unit="ns")),
        _upper_bound("startTime", _epoch_text(end_time, unit="ns")),
    )
    rows = _scan_rows(
        dataset,
        columns=[
            "traceId",
            "spanId",
            "parentSpanId",
            "spanName",
            "startTime",
            "duration",
            "serviceName",
            "statusCode",
            "statusMessage",
            "attributes",
            "events",
        ],
        expression=expression,
        contains=(
            ("statusMessage", keyword),
            ("attributes", keyword),
            ("events", keyword),
        ),
        contains_mode="any_for_keyword",
        limit=limit,
    )
    return _rows("traces", rows)


@tool(args_schema=EventQuery)
def query_events(
    runtime: ToolRuntime[RCA100Context],
    keyword: str | None = None,
    pod_name: str | None = None,
    level: str | None = None,
    limit: Annotated[int, Field(ge=1, le=300)] = 100,
) -> str:
    """Query Kubernetes events; keyword searches the JSON event body."""

    dataset = _dataset(runtime, "events")
    rows = _scan_rows(
        dataset,
        columns=["eventId", "hostname", "level", "pod_name", "clusterName"],
        expression=_and(_equals("pod_name", pod_name), _equals("level", level)),
        contains=(("eventId", keyword),),
        limit=limit,
    )
    return _rows("events", rows)


@tool(args_schema=AlertQuery)
def query_alerts(
    runtime: ToolRuntime[RCA100Context],
    subject: str | None = None,
    status: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 50,
) -> str:
    """Query the incident alert lifecycle."""

    dataset = _dataset(runtime, "alerts")
    rows = _scan_rows(
        dataset,
        columns=["time", "subject", "severity", "status", "subtype", "labels", "annotations", "data"],
        expression=_and(
            _equals("status", status),
            _lower_bound("time", start_time),
            _upper_bound("time", end_time),
        ),
        contains=(("subject", subject),),
        limit=limit,
    )
    return _rows("alerts", rows)


@tool(args_schema=TopologyQuery)
def query_topology(
    runtime: ToolRuntime[RCA100Context],
    entity_name: str | None = None,
    relation: str | None = None,
    limit: Annotated[int, Field(ge=1, le=500)] = 200,
) -> str:
    """Query entities and dependency edges.

    With no selectors, returns topology statistics plus entity-type and
    relation counts. With an entity name, returns matching entities and their
    adjacent edges.
    """

    topology = json.loads((runtime.context.case_directory / "topology.json").read_text(encoding="utf-8"))
    entities = topology.get("entities", [])
    edges = topology.get("edges", [])
    if entity_name is None and relation is None:
        return _json(
            {
                "source": "topology",
                "stats": topology.get("stats", {}),
                "entity_types": Counter(entity.get("type") for entity in entities),
                "relations": Counter(edge.get("relation") for edge in edges),
            }
        )

    matching_entities = [
        entity
        for entity in entities
        if entity_name is None or entity_name.casefold() in str(entity.get("name", "")).casefold()
    ]
    matching_ids = {entity.get("id") for entity in matching_entities}
    matching_edges = [
        edge
        for edge in edges
        if (relation is None or edge.get("relation") == relation)
        and (not matching_ids or edge.get("src") in matching_ids or edge.get("dst") in matching_ids)
    ]
    return _json(
        {
            "source": "topology",
            "entities": matching_entities[:limit],
            "edges": matching_edges[:limit],
            "matched_entities": len(matching_entities),
            "matched_edges": len(matching_edges),
        }
    )


RCA100_TOOLS = (query_metric, query_logs, query_traces, query_events, query_alerts, query_topology)


def build_rca100_agent_spec(response_format: Any | None = None) -> RuntimeSpec:
    """Contribute RCA100 policy through the runtime's official injection fields."""

    base_spec = build_rca100_runtime_spec(
        tools=RCA100_TOOLS,
        context_schema=RCA100Context,
        response_format=response_format,
    )
    prompt = "\n\n".join(part for part in (base_spec.system_prompt, SRE_SYSTEM_PROMPT) if part)
    return replace(
        base_spec,
        system_prompt=prompt,
        skills=(),
        memory=(),
        permissions=(),
        filesystem_tools=None,
    )


async def run_rca100_agent() -> None:
    """Read one blind request from stdin and emit only the agent prediction."""

    request = RCA100Request.model_validate_json(sys.stdin.read())
    runtime = await build_agent_runtime(build_rca100_agent_spec(ToolStrategy(IncidentDiagnosis)))
    try:
        prediction = await runtime.ainvoke_text(
            _diagnosis_prompt(request),
            protocol="benchmark:rca100",
            thread_id=f"rca100:{request.task_id}",
            run_id=f"rca100:{request.task_id}",
            context=RCA100Context(case_directory=request.case_directory),
            extra_metadata={"benchmark": "rca100", "task_id": request.task_id},
        )
        sys.stdout.write(prediction.strip())
    finally:
        await runtime.aclose()


def _dataset(runtime: ToolRuntime[RCA100Context], source: RCA100Source) -> arrow_dataset.Dataset:
    return arrow_dataset.dataset(runtime.context.case_directory / f"{source}.parquet", format="parquet")


def _scan_rows(
    dataset: arrow_dataset.Dataset,
    *,
    columns: list[str],
    expression: arrow_dataset.Expression | None,
    limit: int,
    contains: tuple[tuple[str, str | None], ...] = (),
    contains_mode: Literal["all", "any_for_keyword"] = "all",
) -> list[dict[str, Any]]:
    active_contains = tuple((column, value) for column, value in contains if value)
    compute = cast(Any, arrow_compute)
    rows: list[dict[str, Any]] = []
    for batch in dataset.scanner(columns=columns, filter=expression, batch_size=8192).to_batches():
        filtered = batch
        if active_contains:
            masks = [
                compute.fill_null(
                    compute.match_substring(filtered[column], value, ignore_case=True),
                    False,
                )
                for column, value in active_contains
            ]
            mask = masks[0]
            for candidate in masks[1:]:
                mask = (
                    compute.or_(mask, candidate)
                    if contains_mode == "any_for_keyword"
                    else compute.and_(mask, candidate)
                )
            filtered = filtered.filter(mask)
        remaining = limit - len(rows)
        rows.extend(filtered.slice(0, remaining).to_pylist())
        if len(rows) >= limit:
            break
    return rows


def _equals(column: str, value: object | None) -> arrow_dataset.Expression | None:
    return None if value is None else arrow_dataset.field(column) == value


def _lower_bound(column: str, value: object | None) -> arrow_dataset.Expression | None:
    return None if value is None else arrow_dataset.field(column) >= value


def _upper_bound(column: str, value: object | None) -> arrow_dataset.Expression | None:
    return None if value is None else arrow_dataset.field(column) <= value


def _and(*expressions: arrow_dataset.Expression | None) -> arrow_dataset.Expression | None:
    result = None
    for expression in expressions:
        if expression is not None:
            result = expression if result is None else result & expression
    return result


def _epoch(value: str | None, *, unit: Literal["us", "ns"]) -> int | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    timestamp = datetime.fromisoformat(normalized).timestamp()
    multiplier = 1_000_000 if unit == "us" else 1_000_000_000
    return int(timestamp * multiplier)


def _epoch_text(value: str | None, *, unit: Literal["ns"]) -> str | None:
    converted = _epoch(value, unit=unit)
    return None if converted is None else str(converted)


def _rows(source: str, rows: list[dict[str, Any]]) -> str:
    return _json({"source": source, "returned_rows": len(rows), "rows": rows})


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _diagnosis_prompt(request: RCA100Request) -> str:
    incident = {
        key: request.task[key]
        for key in (
            "alert_title",
            "alert_trigger_time",
            "alert_window",
            "alert_entity",
            "region_id",
            "alert_event_id",
            "alert_trans_id",
        )
        if request.task.get(key) not in (None, "", {}, [])
    }
    return f"""Investigate this production incident.

Incident context:
{json.dumps(incident, ensure_ascii=False)}

Available observation fields:
{json.dumps(request.parquet_schemas, ensure_ascii=False)}

Use query_metric, query_logs, and query_traces for the three primary
modalities. Use query_events, query_alerts, and query_topology for supporting
causal evidence. Return exactly one JSON object matching this schema, without
Markdown or commentary:
{json.dumps(IncidentDiagnosis.model_json_schema(), ensure_ascii=False)}
"""
