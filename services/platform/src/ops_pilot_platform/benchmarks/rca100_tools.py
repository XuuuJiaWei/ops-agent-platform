"""Read-only observability tools contributed by the RCA100 benchmark host."""

import json
from collections import Counter, defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from statistics import fmean
from threading import RLock
from typing import Annotated, Any, Literal, cast

import pyarrow.compute as arrow_compute
import pyarrow.dataset as arrow_dataset
from langchain.agents.middleware import AgentMiddleware
from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command
from pydantic import Field

RCA100Source = Literal["metrics", "logs", "traces", "events", "alerts"]
Direction = Literal["forward", "backward"]
Domain = Literal["apm", "k8s"]

_DATA_TIMEZONE = timezone(timedelta(hours=8))
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 100
_MESSAGE_LIMIT = 500
_RCA100_TOOL_NAMES = frozenset(
    {
        "list_metric_names",
        "query_alerts",
        "query_events",
        "query_log_stats",
        "query_logs",
        "query_metric",
        "query_topology",
        "query_traces",
    }
)

StartTime = Annotated[datetime, Field(description="Inclusive RFC 3339 start time with a UTC offset.")]
EndTime = Annotated[datetime, Field(description="Inclusive RFC 3339 end time with a UTC offset.")]
ResultLimit = Annotated[int, Field(ge=1, le=_MAX_LIMIT, description="Maximum records to return.")]


@dataclass
class RCA100Context:
    """Per-run dataset dependency hidden from model-visible tool schemas."""

    case_directory: Path
    _tool_results: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _tool_results_lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def cached_tool_result(self, key: str) -> str | None:
        with self._tool_results_lock:
            return self._tool_results.get(key)

    def remember_tool_result(self, key: str, content: str) -> None:
        with self._tool_results_lock:
            self._tool_results[key] = content


class RCA100ToolCacheMiddleware(AgentMiddleware):
    """Deduplicate successful idempotent observation calls within one run."""

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        name = str(request.tool_call.get("name", ""))
        context = request.runtime.context
        if name not in _RCA100_TOOL_NAMES or not isinstance(context, RCA100Context):
            return await handler(request)

        key = _tool_cache_key(name, request.tool_call.get("args"))
        if context.cached_tool_result(key) is not None:
            return ToolMessage(
                name=name,
                tool_call_id=str(request.tool_call["id"]),
                status="success",
                content=_success(
                    data={
                        "cache_hit": True,
                        "message": "This identical read-only query already completed successfully.",
                    },
                    meta={"source": name, "query_fingerprint": key[-12:]},
                    warnings=[
                        "Reuse the earlier ToolMessage for this query. Repeating it cannot produce new evidence."
                    ],
                ),
            )

        result = await handler(request)
        if isinstance(result, ToolMessage) and result.status == "success" and isinstance(result.content, str):
            context.remember_tool_result(key, result.content)
        return result


@tool
def list_metric_names(
    runtime: ToolRuntime[RCA100Context],
    entity_domain: Annotated[Domain | None, Field(description="Optional exact observability domain.")] = None,
    entity_set: Annotated[str | None, Field(min_length=1, description="Optional exact entity-set name.")] = None,
    entity_name: Annotated[str | None, Field(min_length=1, description="Optional exact entity name.")] = None,
    entity_id: Annotated[str | None, Field(min_length=1, description="Optional exact entity identifier.")] = None,
    limit: Annotated[int, Field(ge=1, le=_MAX_LIMIT, description="Maximum metric names to return.")] = 50,
) -> str:
    """List metric names before querying samples; this tool never returns raw samples."""

    dataset = _dataset(runtime, "metrics")
    expression = _and(
        _equals("domain", entity_domain),
        _equals("entity_set", entity_set),
        _equals("entity_name", entity_name),
        _equals("entity_id", entity_id),
    )
    table = dataset.to_table(columns=["time", "metric"], filter=expression)
    counts = Counter(value for value in table["metric"].to_pylist() if value)
    names = sorted(counts)
    returned = names[:limit]
    return _success(
        data={"metric_names": [{"name": name, "samples": counts[name]} for name in returned]},
        meta={
            "source": "metrics",
            "returned": len(returned),
            "total": len(names),
            "limit": limit,
            "truncated": len(names) > limit,
            "available_time_range": _time_range(table["time"], unit="us"),
            "filters": _present(
                entity_domain=entity_domain,
                entity_set=entity_set,
                entity_name=entity_name,
                entity_id=entity_id,
            ),
        },
        empty_message="No metric names matched these selectors. Broaden one selector before retrying.",
    )


@tool
def query_metric(
    runtime: ToolRuntime[RCA100Context],
    metric: Annotated[str, Field(min_length=1, description="One exact metric name returned by list_metric_names.")],
    start_time: StartTime,
    end_time: EndTime,
    entity_name: Annotated[str | None, Field(min_length=1, description="Optional exact entity name.")] = None,
    entity_id: Annotated[str | None, Field(min_length=1, description="Optional exact entity identifier.")] = None,
    entity_domain: Annotated[Domain | None, Field(description="Optional exact observability domain.")] = None,
    entity_set: Annotated[str | None, Field(min_length=1, description="Optional exact entity-set name.")] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum distinct time series to return.")] = 10,
    sample_limit: Annotated[int, Field(ge=2, le=100, description="Maximum sampled points per series.")] = 20,
) -> str:
    """Query one exact metric over a bounded time range and return compact Prometheus-style series."""

    dataset = _dataset(runtime, "metrics")
    expression = _and(
        _equals("metric", metric),
        _equals("entity_name", entity_name),
        _equals("entity_id", entity_id),
        _equals("domain", entity_domain),
        _equals("entity_set", entity_set),
        _lower_bound("time", _epoch(start_time, unit="us")),
        _upper_bound("time", _epoch(end_time, unit="us")),
    )
    table = dataset.to_table(
        columns=["time", "domain", "entity_set", "entity_id", "entity_name", "metric", "value", "service"],
        filter=expression,
    )
    groups: dict[tuple[str, ...], list[tuple[int, float]]] = defaultdict(list)
    labels: dict[tuple[str, ...], dict[str, str]] = {}
    for row in table.to_pylist():
        key = tuple(
            str(row.get(field) or "") for field in ("domain", "entity_set", "entity_id", "entity_name", "service")
        )
        groups[key].append((int(row["time"]), float(row["value"])))
        labels[key] = {
            name: str(row[name])
            for name in ("domain", "entity_set", "entity_id", "entity_name", "service")
            if row.get(name) not in (None, "")
        }

    ordered_keys = sorted(groups, key=lambda key: (-len(groups[key]), key))
    result: list[dict[str, Any]] = []
    samples_were_reduced = False
    for key in ordered_keys[:limit]:
        samples = sorted(groups[key])
        selected = _evenly_sample(samples, sample_limit)
        samples_were_reduced = samples_were_reduced or len(selected) < len(samples)
        values = [value for _, value in samples]
        result.append(
            {
                "metric": {"__name__": metric, **labels[key]},
                "values": [[_iso_epoch(timestamp, unit="us"), value] for timestamp, value in selected],
                "statistics": {
                    "samples": len(samples),
                    "min": min(values),
                    "max": max(values),
                    "mean": fmean(values),
                    "first": values[0],
                    "last": values[-1],
                    "delta": values[-1] - values[0],
                    "largest_changes": _largest_changes(samples),
                },
            }
        )

    return _success(
        data={"resultType": "matrix", "result": result},
        meta={
            "source": "metrics",
            "returned_series": len(result),
            "total_series": len(groups),
            "total_samples": table.num_rows,
            "limit": limit,
            "sample_limit": sample_limit,
            "truncated": len(groups) > limit or samples_were_reduced,
            "time_range": _window(start_time, end_time),
            "filters": _present(
                metric=metric,
                entity_domain=entity_domain,
                entity_set=entity_set,
                entity_name=entity_name,
                entity_id=entity_id,
            ),
        },
        empty_message="No samples matched this valid query. Use list_metric_names or change one selector/time range.",
    )


@tool
def query_log_stats(
    runtime: ToolRuntime[RCA100Context],
    start_time: StartTime,
    end_time: EndTime,
    keyword: Annotated[str | None, Field(min_length=1, description="Case-insensitive log text fragment.")] = None,
    pod_name: Annotated[str | None, Field(min_length=1, description="Optional exact pod name.")] = None,
    namespace: Annotated[str | None, Field(min_length=1, description="Optional exact namespace.")] = None,
) -> str:
    """Count matching log streams before retrieving lines, following Grafana Loki's low-cost stats pattern."""

    rows = _all_log_rows(runtime, start_time, end_time, keyword, pod_name, namespace)
    return _success(
        data={
            "matching_lines": len(rows),
            "pods": _top_counts(row.get("_pod_name_") for row in rows),
            "namespaces": _top_counts(row.get("_namespace_") for row in rows),
            "containers": _top_counts(row.get("_container_name_") for row in rows),
        },
        meta={
            "source": "logs",
            "time_range": _window(start_time, end_time),
            "filters": _present(keyword=keyword, pod_name=pod_name, namespace=namespace),
        },
        empty_message=(
            "No log lines matched this valid query. Change one selector or time range; "
            "an unchanged retry is deterministic."
        ),
    )


@tool
def query_logs(
    runtime: ToolRuntime[RCA100Context],
    start_time: StartTime,
    end_time: EndTime,
    keyword: Annotated[str | None, Field(min_length=1, description="Case-insensitive log text fragment.")] = None,
    pod_name: Annotated[str | None, Field(min_length=1, description="Optional exact pod name.")] = None,
    namespace: Annotated[str | None, Field(min_length=1, description="Optional exact namespace.")] = None,
    limit: ResultLimit = _DEFAULT_LIMIT,
    direction: Annotated[Direction, Field(description="Newest-first or oldest-first ordering.")] = "backward",
) -> str:
    """Return bounded application log lines; use query_log_stats first to avoid empty-stream searches."""

    rows = _all_log_rows(runtime, start_time, end_time, keyword, pod_name, namespace)
    ordered = sorted(rows, key=lambda row: str(row.get("_time_", "")), reverse=direction == "backward")
    selected = ordered[: limit + 1]
    truncated = len(selected) > limit
    entries = [
        {
            "timestamp": row.get("_time_"),
            "namespace": row.get("_namespace_"),
            "pod": row.get("_pod_name_"),
            "container": row.get("_container_name_"),
            "message": _clip(row.get("content")),
        }
        for row in selected[:limit]
    ]
    return _success(
        data={"resultType": "streams", "result": entries},
        meta={
            "source": "logs",
            "returned": len(entries),
            "limit": limit,
            "direction": direction,
            "truncated": truncated,
            "time_range": _window(start_time, end_time),
            "filters": _present(keyword=keyword, pod_name=pod_name, namespace=namespace),
        },
        empty_message=(
            "No log lines matched this valid query. Change one selector or time range; "
            "an unchanged retry is deterministic."
        ),
    )


@tool
def query_traces(
    runtime: ToolRuntime[RCA100Context],
    start_time: StartTime,
    end_time: EndTime,
    service_name: Annotated[str | None, Field(min_length=1, description="Optional exact service name.")] = None,
    span_name: Annotated[str | None, Field(min_length=1, description="Optional exact span operation.")] = None,
    trace_id: Annotated[str | None, Field(min_length=1, description="Optional exact trace identifier.")] = None,
    status_code: Annotated[str | None, Field(min_length=1, description="Optional exact span status code.")] = None,
    keyword: Annotated[str | None, Field(min_length=1, description="Text in status, attributes, or events.")] = None,
    limit: ResultLimit = _DEFAULT_LIMIT,
    direction: Annotated[Direction, Field(description="Newest-first or oldest-first ordering.")] = "backward",
) -> str:
    """Search bounded trace spans; pass a returned trace_id to retrieve that trace's spans."""

    dataset = _dataset(runtime, "traces")
    expression = _and(
        _equals("serviceName", service_name),
        _equals("spanName", span_name),
        _equals("traceId", trace_id),
        _equals("statusCode", status_code),
        _lower_bound("startTime", str(_epoch(start_time, unit="ns"))),
        _upper_bound("startTime", str(_epoch(end_time, unit="ns"))),
    )
    rows, truncated = _scan_rows(
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
        contains=(("statusMessage", keyword), ("attributes", keyword), ("events", keyword)),
        contains_mode="any_for_keyword",
        limit=limit,
        direction=direction,
        order_column="startTime",
    )
    spans = [_compact_span(row) for row in rows]
    return _success(
        data={"resultType": "spans", "result": spans},
        meta={
            "source": "traces",
            "returned": len(spans),
            "limit": limit,
            "direction": direction,
            "truncated": truncated,
            "time_range": _window(start_time, end_time),
            "filters": _present(
                service_name=service_name,
                span_name=span_name,
                trace_id=trace_id,
                status_code=status_code,
                keyword=keyword,
            ),
        },
        empty_message=(
            "No spans matched this valid query. Change one selector or time range; an unchanged retry is deterministic."
        ),
    )


@tool
def query_events(
    runtime: ToolRuntime[RCA100Context],
    start_time: StartTime,
    end_time: EndTime,
    keyword: Annotated[str | None, Field(min_length=1, description="Text in the reason or message.")] = None,
    pod_name: Annotated[str | None, Field(min_length=1, description="Optional exact pod name.")] = None,
    level: Annotated[str | None, Field(min_length=1, description="Optional exact event level.")] = None,
    limit: ResultLimit = _DEFAULT_LIMIT,
    direction: Annotated[Direction, Field(description="Newest-first or oldest-first ordering.")] = "backward",
) -> str:
    """Query compact Kubernetes event records over a bounded time range."""

    table = _dataset(runtime, "events").to_table(columns=["eventId", "hostname", "level", "pod_name", "clusterName"])
    events: list[dict[str, Any]] = []
    for row in table.to_pylist():
        payload = _json_object(row.get("eventId"))
        timestamp = _parse_time(
            payload.get("lastTimestamp")
            or payload.get("eventTime")
            or cast(dict[str, Any], payload.get("metadata") or {}).get("creationTimestamp")
        )
        if timestamp is None or not _within(timestamp, start_time, end_time):
            continue
        reason = str(payload.get("reason") or "")
        message = str(payload.get("message") or "")
        if keyword and keyword.casefold() not in f"{reason} {message}".casefold():
            continue
        if pod_name and row.get("pod_name") != pod_name:
            continue
        if level and row.get("level") != level:
            continue
        involved = cast(dict[str, Any], payload.get("involvedObject") or {})
        events.append(
            {
                "timestamp": timestamp.isoformat(),
                "level": row.get("level"),
                "reason": reason,
                "message": _clip(message),
                "count": payload.get("count"),
                "namespace": involved.get("namespace"),
                "pod": row.get("pod_name"),
                "host": row.get("hostname"),
                "cluster": row.get("clusterName"),
            }
        )
    events.sort(key=lambda event: str(event["timestamp"]), reverse=direction == "backward")
    selected = events[:limit]
    return _success(
        data={"resultType": "events", "result": selected},
        meta={
            "source": "events",
            "returned": len(selected),
            "limit": limit,
            "direction": direction,
            "truncated": len(events) > limit,
            "time_range": _window(start_time, end_time),
            "filters": _present(keyword=keyword, pod_name=pod_name, level=level),
        },
        empty_message="No Kubernetes events matched this valid query. Change one selector or time range.",
    )


@tool
def query_alerts(
    runtime: ToolRuntime[RCA100Context],
    start_time: StartTime,
    end_time: EndTime,
    subject: Annotated[str | None, Field(min_length=1, description="Case-insensitive subject fragment.")] = None,
    status: Annotated[str | None, Field(min_length=1, description="Optional exact lifecycle status.")] = None,
    limit: ResultLimit = _DEFAULT_LIMIT,
    direction: Annotated[Direction, Field(description="Newest-first or oldest-first ordering.")] = "backward",
) -> str:
    """Query compact alert lifecycle records over a bounded time range."""

    dataset = _dataset(runtime, "alerts")
    expression = _and(
        _equals("status", status),
        _lower_bound("time_s", int(start_time.timestamp())),
        _upper_bound("time_s", int(end_time.timestamp())),
    )
    rows, truncated = _scan_rows(
        dataset,
        columns=["time_s", "subject", "severity", "status", "subtype", "resource", "annotations", "data", "id"],
        expression=expression,
        contains=(("subject", subject),),
        limit=limit,
        direction=direction,
        order_column="time_s",
    )
    alerts = [_compact_alert(row) for row in rows]
    return _success(
        data={"resultType": "alerts", "result": alerts},
        meta={
            "source": "alerts",
            "returned": len(alerts),
            "limit": limit,
            "direction": direction,
            "truncated": truncated,
            "time_range": _window(start_time, end_time),
            "filters": _present(subject=subject, status=status),
        },
        empty_message="No alerts matched this valid query. Change one selector or time range.",
    )


@tool
def query_topology(
    runtime: ToolRuntime[RCA100Context],
    entity_name: Annotated[str | None, Field(min_length=1, description="Entity-name fragment.")] = None,
    entity_id: Annotated[str | None, Field(min_length=1, description="Exact entity identifier.")] = None,
    entity_type: Annotated[str | None, Field(min_length=1, description="Optional exact entity type.")] = None,
    relation: Annotated[str | None, Field(min_length=1, description="Optional exact dependency relation.")] = None,
    limit: ResultLimit = _DEFAULT_LIMIT,
) -> str:
    """Discover topology types or retrieve an entity's compact dependency neighborhood."""

    topology = json.loads((runtime.context.case_directory / "topology.json").read_text(encoding="utf-8"))
    entities = cast(list[dict[str, Any]], topology.get("entities", []))
    edges = cast(list[dict[str, Any]], topology.get("edges", []))
    if not any((entity_name, entity_id, entity_type, relation)):
        return _success(
            data={
                "entities_total": len(entities),
                "edges_total": len(edges),
                "entity_types": dict(Counter(str(entity.get("type")) for entity in entities)),
                "relations": dict(Counter(str(edge.get("relation")) for edge in edges)),
            },
            meta={"source": "topology", "mode": "catalog", "truncated": False},
        )

    matching_entities = [
        entity
        for entity in entities
        if (entity_name is None or entity_name.casefold() in str(entity.get("name", "")).casefold())
        and (entity_id is None or entity.get("id") == entity_id)
        and (entity_type is None or entity.get("type") == entity_type)
    ]
    matching_ids = {entity.get("id") for entity in matching_entities}
    has_entity_filter = any((entity_name, entity_id, entity_type))
    matching_edges = [
        edge
        for edge in edges
        if (relation is None or edge.get("relation") == relation)
        and (not has_entity_filter or edge.get("src") in matching_ids or edge.get("dst") in matching_ids)
    ]
    by_id = {entity.get("id"): entity for entity in entities}
    compact_entities = [_compact_entity(entity) for entity in matching_entities[:limit]]
    compact_edges = [_compact_edge(edge, by_id) for edge in matching_edges[:limit]]
    return _success(
        data={"entities": compact_entities, "edges": compact_edges},
        meta={
            "source": "topology",
            "mode": "neighborhood",
            "returned_entities": len(compact_entities),
            "total_entities": len(matching_entities),
            "returned_edges": len(compact_edges),
            "total_edges": len(matching_edges),
            "limit": limit,
            "truncated": len(matching_entities) > limit or len(matching_edges) > limit,
            "filters": _present(
                entity_name=entity_name,
                entity_id=entity_id,
                entity_type=entity_type,
                relation=relation,
            ),
        },
        empty_message="No topology entity or edge matched these selectors. Broaden one selector before retrying.",
    )


RCA100_TOOLS = (
    list_metric_names,
    query_metric,
    query_log_stats,
    query_logs,
    query_traces,
    query_events,
    query_alerts,
    query_topology,
)


def _dataset(runtime: ToolRuntime[RCA100Context], source: RCA100Source) -> arrow_dataset.Dataset:
    return arrow_dataset.dataset(runtime.context.case_directory / f"{source}.parquet", format="parquet")


def _all_log_rows(
    runtime: ToolRuntime[RCA100Context],
    start_time: datetime,
    end_time: datetime,
    keyword: str | None,
    pod_name: str | None,
    namespace: str | None,
) -> list[dict[str, Any]]:
    dataset = _dataset(runtime, "logs")
    expression = _and(
        _equals("_pod_name_", pod_name),
        _equals("_namespace_", namespace),
        _lower_bound("_time_", _local_time_text(start_time)),
        _upper_bound("_time_", _local_time_text(end_time)),
    )
    rows, _ = _scan_rows(
        dataset,
        columns=["_time_", "_namespace_", "_pod_name_", "_container_name_", "content"],
        expression=expression,
        contains=(("content", keyword),),
        limit=None,
        direction="forward",
        order_column="_time_",
    )
    return rows


def _scan_rows(
    dataset: arrow_dataset.Dataset,
    *,
    columns: list[str],
    expression: arrow_dataset.Expression | None,
    limit: int | None,
    direction: Direction,
    order_column: str,
    contains: tuple[tuple[str, str | None], ...] = (),
    contains_mode: Literal["all", "any_for_keyword"] = "all",
) -> tuple[list[dict[str, Any]], bool]:
    active_contains = tuple((column, value) for column, value in contains if value)
    compute = cast(Any, arrow_compute)
    requested = None if limit is None else limit + 1
    rows: list[dict[str, Any]] | deque[dict[str, Any]]
    rows = deque(maxlen=requested) if direction == "backward" and requested is not None else []
    for batch in dataset.scanner(columns=columns, filter=expression, batch_size=8192).to_batches():
        filtered = batch
        if active_contains:
            masks = [
                compute.fill_null(compute.match_substring(filtered[column], value, ignore_case=True), False)
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
        batch_rows = filtered.to_pylist()
        rows.extend(batch_rows)
        if requested is not None and direction == "forward" and len(rows) >= requested:
            break

    ordered = sorted(list(rows), key=lambda row: row.get(order_column) or 0, reverse=direction == "backward")
    if limit is None:
        return ordered, False
    return ordered[:limit], len(ordered) > limit


def _compact_span(row: dict[str, Any]) -> dict[str, Any]:
    attributes = _json_object(row.get("attributes"))
    selected_attributes = {
        key: value
        for key, value in attributes.items()
        if key.startswith(("error.", "exception.", "http.", "rpc.", "db.", "messaging."))
        or key in {"rpc", "call.type", "call.kind"}
    }
    raw_events = _json_value(row.get("events"), default=[])
    event_names = [str(event.get("name")) for event in raw_events if isinstance(event, dict) and event.get("name")]
    start = int(row["startTime"])
    return {
        "trace_id": row.get("traceId"),
        "span_id": row.get("spanId"),
        "parent_span_id": row.get("parentSpanId") or None,
        "timestamp": _iso_epoch(start, unit="ns"),
        "duration_ms": int(row.get("duration") or 0) / 1_000_000,
        "service": row.get("serviceName"),
        "operation": row.get("spanName"),
        "status_code": row.get("statusCode"),
        "status_message": _clip(row.get("statusMessage")),
        "attributes": selected_attributes,
        "events": event_names[:10],
    }


def _compact_alert(row: dict[str, Any]) -> dict[str, Any]:
    resource = _json_object(row.get("resource"))
    annotations = _json_object(row.get("annotations"))
    data = _json_object(row.get("data"))
    entity = cast(dict[str, Any], resource.get("entity") or {})
    details = data.get("detailValue")
    return {
        "id": row.get("id"),
        "timestamp": datetime.fromtimestamp(int(row["time_s"]), UTC).isoformat(),
        "subject": row.get("subject"),
        "severity": row.get("severity"),
        "status": row.get("status"),
        "subtype": row.get("subtype"),
        "entity": {
            key: entity.get(key) for key in ("domain", "entity_id", "entity_type") if entity.get(key) not in (None, "")
        },
        "message": _clip(annotations.get("message")),
        "current_value": annotations.get("current_value") or data.get("currentValue"),
        "details": details[:5] if isinstance(details, list) else [],
    }


def _compact_entity(entity: dict[str, Any]) -> dict[str, Any]:
    props = cast(dict[str, Any], entity.get("props") or {})
    useful_props = {
        key: props[key]
        for key in ("service", "language", "namespace", "pod", "node", "operation")
        if key in props and props[key] not in (None, "")
    }
    return {"id": entity.get("id"), "type": entity.get("type"), "name": entity.get("name"), "props": useful_props}


def _compact_edge(edge: dict[str, Any], by_id: dict[Any, dict[str, Any]]) -> dict[str, Any]:
    source = by_id.get(edge.get("src"), {})
    target = by_id.get(edge.get("dst"), {})
    return {
        "source": {"id": edge.get("src"), "type": edge.get("src_type"), "name": source.get("name")},
        "target": {"id": edge.get("dst"), "type": edge.get("dst_type"), "name": target.get("name")},
        "relation": edge.get("relation"),
    }


def _success(
    *,
    data: Any,
    meta: dict[str, Any],
    empty_message: str | None = None,
    warnings: list[str] | None = None,
) -> str:
    result_warnings = list(warnings or ())
    if empty_message and _is_empty(data):
        result_warnings.append(empty_message)
    return json.dumps(
        {"status": "success", "data": data, "meta": meta, "warnings": result_warnings},
        ensure_ascii=False,
    )


def _is_empty(data: Any) -> bool:
    if isinstance(data, list):
        return not data
    if isinstance(data, dict):
        if "entities" in data and "edges" in data:
            return not data["entities"] and not data["edges"]
        for key in ("result", "metric_names", "entities", "edges"):
            if key in data:
                return not data[key]
        if "matching_lines" in data:
            return data["matching_lines"] == 0
    return False


def _top_counts(values: Any, limit: int = 10) -> list[dict[str, Any]]:
    counts = Counter(str(value) for value in values if value not in (None, ""))
    return [{"value": value, "count": count} for value, count in counts.most_common(limit)]


def _evenly_sample(samples: list[tuple[int, float]], limit: int) -> list[tuple[int, float]]:
    if len(samples) <= limit:
        return samples
    last = len(samples) - 1
    indices = sorted({round(index * last / (limit - 1)) for index in range(limit)})
    return [samples[index] for index in indices]


def _largest_changes(samples: list[tuple[int, float]], limit: int = 3) -> list[dict[str, Any]]:
    changes = [
        {
            "from": _iso_epoch(before_time, unit="us"),
            "to": _iso_epoch(after_time, unit="us"),
            "before": before_value,
            "after": after_value,
            "delta": after_value - before_value,
        }
        for (before_time, before_value), (after_time, after_value) in zip(samples, samples[1:], strict=False)
    ]
    return sorted(changes, key=lambda change: abs(float(change["delta"])), reverse=True)[:limit]


def _tool_cache_key(name: str, arguments: Any) -> str:
    canonical = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"{name}:{sha256(canonical.encode('utf-8')).hexdigest()}"


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


def _epoch(value: datetime, *, unit: Literal["us", "ns"]) -> int:
    multiplier = 1_000_000 if unit == "us" else 1_000_000_000
    return int(value.timestamp() * multiplier)


def _iso_epoch(value: int, *, unit: Literal["us", "ns"]) -> str:
    divisor = 1_000_000 if unit == "us" else 1_000_000_000
    return datetime.fromtimestamp(value / divisor, UTC).isoformat()


def _local_time_text(value: datetime) -> str:
    return value.astimezone(_DATA_TIMEZONE).isoformat()


def _window(start_time: datetime, end_time: datetime) -> dict[str, str]:
    return {"start": start_time.isoformat(), "end": end_time.isoformat()}


def _time_range(values: Any, *, unit: Literal["us", "ns"]) -> dict[str, str] | None:
    compute = cast(Any, arrow_compute)
    bounds = cast(dict[str, int | None], compute.min_max(values).as_py())
    if bounds.get("min") is None or bounds.get("max") is None:
        return None
    return {
        "start": _iso_epoch(cast(int, bounds["min"]), unit=unit),
        "end": _iso_epoch(cast(int, bounds["max"]), unit=unit),
    }


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _within(value: datetime, start_time: datetime, end_time: datetime) -> bool:
    return start_time <= value.astimezone(start_time.tzinfo) <= end_time


def _json_value(value: Any, *, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def _json_object(value: Any) -> dict[str, Any]:
    parsed = _json_value(value, default={})
    return parsed if isinstance(parsed, dict) else {}


def _clip(value: Any, limit: int = _MESSAGE_LIMIT) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _present(**values: object | None) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None}
