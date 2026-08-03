#!/usr/bin/env python3
"""Build and parse Dynatrace MongoDB Atlas host discovery queries."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HOST_LIST_METRIC = "mongodbatlas.db.counts"
DEFAULT_ENVIRONMENT_ALIAS = "frankfurt"
DEFAULT_FROM = "now-30m"
DEFAULT_TO = "now"
DEFAULT_RESOLUTION = "30m"

HOST_KEYS = (
    "mongodb_atlas.host.name",
    "mongodb_atlas.process.name",
    "mongodb_atlas.host.id",
    "mongodb_atlas.process.id",
    "host.name",
    "process.name",
)
DB_KEYS = ("mongodb_atlas.db.name", "db.name", "database", "database.name")
ROLE_KEYS = (
    "mongodb_atlas.host.role",
    "mongodb_atlas.process.role",
    "mongodb_atlas.process.type_name",
    "mongodb_atlas.replica_set.role",
    "mongodb_atlas.replica_state_name",
    "mongodb_atlas.replica_state",
    "replica_state",
    "replica_state_name",
    "role",
    "state",
)

ROLE_PROBE_METRICS = (
    "mongodbatlas.process.oplog.time",
    "mongodbatlas.process.oplog.rate",
)

ROLE_PROBE_SPLIT_DIMENSIONS = {
    "mongodbatlas.process.oplog.time": (
        "mongodb_atlas.host.name",
        "mongodb_atlas.process.type_name",
        "oplog_type",
    ),
    "mongodbatlas.process.oplog.rate": (
        "mongodb_atlas.host.name",
        "mongodb_atlas.process.type_name",
    ),
}

NUMERIC_REPLICA_STATE = {
    1: "primary",
    2: "secondary",
    3: "recovering",
    5: "startup2",
    6: "unknown",
    7: "arbiter",
    8: "down",
    9: "rollback",
}


@dataclass
class HostRecord:
    host: str
    databases: set[str] = field(default_factory=set)
    metrics_seen: set[str] = field(default_factory=set)
    latest_values: dict[str, float] = field(default_factory=dict)
    role: str = "unknown"
    role_confidence: str = "none"
    evidence: list[str] = field(default_factory=list)

    def set_role(self, role: str, confidence: str, evidence: str) -> None:
        rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        if rank[confidence] >= rank.get(self.role_confidence, 0):
            self.role = role
            self.role_confidence = confidence
        if evidence not in self.evidence:
            self.evidence.append(evidence)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service_name")
    parser.add_argument("--db-name")
    parser.add_argument("--environment-alias", default=DEFAULT_ENVIRONMENT_ALIAS)
    parser.add_argument("--from", dest="from_time", default=DEFAULT_FROM)
    parser.add_argument("--to", dest="to_time", default=DEFAULT_TO)
    parser.add_argument("--resolution", default=DEFAULT_RESOLUTION)
    parser.add_argument("--metric", action="append", dest="metrics", default=[])
    parser.add_argument("--dry-run", action="store_true", help="Print query payloads without calling Dynatrace")
    parser.add_argument(
        "--response-file",
        help="Optional combined Dynatrace response JSON file. Use '-' to read stdin explicitly.",
    )
    args = parser.parse_args()
    response = load_optional_response(args.response_file)
    if response is not None:
        print_json(parse_responses(args, response))
    elif args.dry_run:
        print_json(build_discovery_plan(args))
    else:
        print_json(run_direct_discovery(args))
    return 0


def build_discovery_plan(args: argparse.Namespace) -> dict[str, Any]:
    host_query = build_host_query(args)["host_list_query"]
    role_queries = build_role_probes(args)["role_probe_queries"]
    return {
        "mode": "dry_run",
        "service_name": args.service_name,
        "db_name": args.db_name or args.service_name,
        "environment_alias": args.environment_alias,
        "dynatrace_api_calls": [
            {
                "name": "host_list",
                "arguments": host_query,
            },
            *[
                {
                    "name": f"role_metrics.{query['metricSelector'].split(':', 1)[0]}",
                    "arguments": query,
                }
                for query in role_queries
            ],
        ],
        "note": "Default execution calls Dynatrace directly; dry-run only prints selectors.",
    }


def run_direct_discovery(args: argparse.Namespace) -> dict[str, Any]:
    """Run the full host/role workflow directly against Dynatrace Metrics API v2."""

    client = DynatraceClient.from_environment(args.environment_alias)
    host_query = build_host_query(args)["host_list_query"]
    host_response = client.query_metrics(host_query)
    role_responses: dict[str, Any] = {}
    for query in build_role_probes(args)["role_probe_queries"]:
        metric_name = query["metricSelector"].split(":", 1)[0]
        role_responses[metric_name] = client.query_metrics(query, fail_soft=True)
    return parse_responses(
        args,
        {
            "host_list": host_response,
            "role_metrics": role_responses,
        },
    )


class DynatraceClient:
    def __init__(self, *, base_url: str, token: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_environment(cls, environment_alias: str) -> DynatraceClient:
        config = load_dynatrace_config(environment_alias)
        token = config.get("apiToken") or first_env(
            f"DT_{env_key(environment_alias)}_TOKEN",
            "DT_API_TOKEN",
            "DYNATRACE_API_TOKEN",
        )
        if not token:
            raise SystemExit(f"Missing Dynatrace token. Set DT_{env_key(environment_alias)}_TOKEN.")
        endpoint = config.get("apiEndpointUrl") or config.get("dynatraceUrl")
        environment_id = config.get("environmentId")
        if not endpoint:
            raise SystemExit("Missing Dynatrace endpoint. Set DT_CONFIG_FILE or DT_<ALIAS>_URL.")
        return cls(base_url=metrics_api_base(endpoint, environment_id), token=token)

    def query_metrics(self, payload: dict[str, str], *, fail_soft: bool = False) -> dict[str, Any]:
        query = {key: value for key, value in payload.items() if key != "environment_alias"}
        url = f"{self.base_url}/metrics/query?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Api-Token {self.token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if not fail_soft:
                raise SystemExit(f"Dynatrace metrics query failed ({exc.code}): {body}") from exc
            return {"result": [], "warnings": [f"{exc.code}: {body}"], "_failed_query": payload}
        except urllib.error.URLError as exc:
            if not fail_soft:
                raise SystemExit(f"Dynatrace metrics query failed: {exc.reason}") from exc
            return {"result": [], "warnings": [str(exc.reason)], "_failed_query": payload}


def build_host_query(args: argparse.Namespace) -> dict[str, Any]:
    db_name = args.db_name or args.service_name
    return {
        "service_name": args.service_name,
        "db_name": db_name,
        "host_list_query": metric_query_payload(
            metric_selector=(
                f'{HOST_LIST_METRIC}:filter(eq("mongodb_atlas.db.name",'
                f'"{escape_selector_value(db_name)}"))'
                ':splitBy("mongodb_atlas.db.name","mongodb_atlas.host.name")'
            ),
            args=args,
        ),
    }


def build_role_probes(args: argparse.Namespace) -> dict[str, Any]:
    db_name = args.db_name or args.service_name
    metrics = tuple(dict.fromkeys([*args.metrics, *ROLE_PROBE_METRICS]))
    return {
        "service_name": args.service_name,
        "db_name": db_name,
        "role_probe_queries": [
            metric_query_payload(
                metric_selector=role_metric_selector(metric),
                args=args,
            )
            for metric in metrics
        ],
        "notes": [
            "Use these host-level probes only if the host-list response has no explicit role/state dimension.",
            "The process.type_name dimension can provide primary/secondary evidence when "
            "Dynatrace exports it for MongoDB Atlas process metrics.",
        ],
    }


def role_metric_selector(metric: str) -> str:
    dimensions = ROLE_PROBE_SPLIT_DIMENSIONS.get(metric, ("mongodb_atlas.host.name",))
    split_by = ",".join(f'"{dimension}"' for dimension in dimensions)
    return f"{metric}:splitBy({split_by})"


def metric_query_payload(metric_selector: str, args: argparse.Namespace) -> dict[str, str]:
    return {
        "metricSelector": metric_selector,
        "from": args.from_time,
        "to": args.to_time,
        "resolution": args.resolution,
        "environment_alias": args.environment_alias,
    }


def parse_responses(args: argparse.Namespace, raw_payload: Any) -> dict[str, Any]:
    payload = unwrap_response_payload(raw_payload)
    db_name = args.db_name or args.service_name
    host_payload, role_payloads = split_input_payload(payload)
    records: dict[str, HostRecord] = {}

    consume_metrics(host_payload, records, db_name=db_name, host_list=True)
    for label, role_payload in role_payloads.items():
        consume_metrics(role_payload, records, db_name=db_name, host_list=False, source_label=label)

    infer_primary_from_secondary_evidence(records)
    hosts = [serialize_record(record) for record in sorted(records.values(), key=lambda item: item.host)]
    primary_hosts = [host["host"] for host in hosts if host["role"] in {"primary", "primary_candidate"}]
    secondary_hosts = [host["host"] for host in hosts if host["role"] in {"secondary", "secondary_candidate"}]
    unknown_hosts = [host["host"] for host in hosts if host["role"] == "unknown"]

    return {
        "service_name": args.service_name,
        "db_name": db_name,
        "environment_alias": args.environment_alias,
        "timeframe": {"from": args.from_time, "to": args.to_time},
        "hosts": hosts,
        "role_relationship": {
            "primary": primary_hosts,
            "secondaries": secondary_hosts,
            "unknown": unknown_hosts,
        },
        "next_actions": next_actions(hosts),
    }


def split_input_payload(payload: Any) -> tuple[Any, dict[str, Any]]:
    if isinstance(payload, dict):
        host_payload = payload.get("host_list") or payload.get("host_response") or payload
        role_payloads = payload.get("role_metrics") or payload.get("role_responses") or {}
        if isinstance(role_payloads, list):
            role_payloads = {f"role_probe_{index}": item for index, item in enumerate(role_payloads)}
        if not isinstance(role_payloads, dict):
            role_payloads = {}
        return host_payload, role_payloads
    return payload, {}


def consume_metrics(
    payload: Any,
    records: dict[str, HostRecord],
    *,
    db_name: str,
    host_list: bool,
    source_label: str | None = None,
) -> None:
    for metric in iter_metric_results(unwrap_response_payload(payload)):
        metric_id = str(metric.get("metricId") or source_label or "unknown")
        for series in metric.get("data") or []:
            dimension_map = normalize_dimension_map(metric, series)
            host = first_dimension(dimension_map, HOST_KEYS)
            if not host:
                continue
            if not host_list and host not in records:
                continue
            record = records.setdefault(host, HostRecord(host=host))
            record.metrics_seen.add(metric_id)
            database = first_dimension(dimension_map, DB_KEYS)
            if database:
                record.databases.add(database)
            elif host_list:
                record.databases.add(db_name)
            latest = latest_numeric(series.get("values"))
            if latest is not None:
                record.latest_values[metric_id] = latest
            apply_role_evidence(record, metric_id, dimension_map, latest)


def apply_role_evidence(
    record: HostRecord, metric_id: str, dimension_map: dict[str, str], latest: float | None
) -> None:
    for key, value in dimension_map.items():
        normalized_key = key.lower()
        if key in ROLE_KEYS or "role" in normalized_key or "replica_state" in normalized_key:
            role = normalize_role(value)
            if role != "unknown":
                record.set_role(role, "high", f"dimension {key}={value} on {metric_id}")
                return

    lowered_metric = metric_id.lower()
    if "replica_state" in lowered_metric and latest is not None:
        role = NUMERIC_REPLICA_STATE.get(int(latest), "unknown")
        if role != "unknown":
            record.set_role(role, "high", f"numeric replica state {latest:g} from {metric_id}")
            return

    if any(token in lowered_metric for token in ("replication", "oplog", "lag")):
        record.set_role("secondary_candidate", "medium", f"secondary-like metric present: {metric_id}")


def infer_primary_from_secondary_evidence(records: dict[str, HostRecord]) -> None:
    if not records:
        return
    secondary_like = {host for host, record in records.items() if record.role in {"secondary", "secondary_candidate"}}
    unknown = [record for host, record in records.items() if host not in secondary_like]
    if len(unknown) == 1 and secondary_like:
        unknown[0].set_role(
            "primary_candidate",
            "medium",
            "only host without secondary-like replication evidence in this discovery set",
        )


def iter_metric_results(payload: Any) -> list[dict[str, Any]]:
    payload = unwrap_response_payload(payload)
    if isinstance(payload, dict) and isinstance(payload.get("result"), list):
        return [item for item in payload["result"] if isinstance(item, dict)]
    if isinstance(payload, dict) and "metricId" in payload:
        return [payload]
    if isinstance(payload, list):
        results: list[dict[str, Any]] = []
        for item in payload:
            results.extend(iter_metric_results(item))
        return results
    if isinstance(payload, dict):
        results = []
        for value in payload.values():
            results.extend(iter_metric_results(value))
        return results
    return []


def normalize_dimension_map(metric: dict[str, Any], series: dict[str, Any]) -> dict[str, str]:
    dimension_map = series.get("dimensionMap")
    if isinstance(dimension_map, dict):
        return {str(key): str(value) for key, value in dimension_map.items() if value is not None}

    dimensions = series.get("dimensions")
    names = metric.get("dimensionNames") or metric.get("dimensions")
    if isinstance(dimensions, list) and isinstance(names, list):
        return {str(key): str(value) for key, value in zip(names, dimensions, strict=False)}
    return {}


def first_dimension(dimension_map: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = dimension_map.get(key)
        if value:
            return value
    for key, value in dimension_map.items():
        lowered = key.lower()
        if any(candidate in lowered for candidate in keys):
            return value
    return None


def latest_numeric(values: Any) -> float | None:
    if not isinstance(values, list):
        return None
    for value in reversed(values):
        if isinstance(value, (int, float)):
            return float(value)
    return None


def normalize_role(value: Any) -> str:
    text = str(value).strip().lower()
    if text in {"1", "primary", "primary_preferred", "primarypreferred"}:
        return "primary"
    if text in {"2", "secondary", "secondary_preferred", "secondarypreferred"}:
        return "secondary"
    if "primary" in text:
        return "primary"
    if "secondary" in text:
        return "secondary"
    if "arbiter" in text:
        return "arbiter"
    return NUMERIC_REPLICA_STATE.get(int(text), "unknown") if text.isdigit() else "unknown"


def serialize_record(record: HostRecord) -> dict[str, Any]:
    return {
        "host": record.host,
        "databases": sorted(record.databases),
        "role": record.role,
        "role_confidence": record.role_confidence,
        "evidence": record.evidence,
        "metrics_seen": sorted(record.metrics_seen),
        "latest_values": record.latest_values,
    }


def next_actions(hosts: list[dict[str, Any]]) -> list[str]:
    if not hosts:
        return ["No hosts were found. Verify the database/service name and timeframe."]
    if any(host["role"] == "unknown" for host in hosts):
        return [
            "Role probes did not find explicit replica-state evidence. Check Dynatrace "
            "metric availability or widen the timeframe.",
            "If an explicit replica-state metric is available, prefer it over replication-lag inference.",
        ]
    return []


def unwrap_response_payload(value: Any) -> Any:
    if isinstance(value, dict) and isinstance(value.get("content"), list):
        texts = [item.get("text") for item in value["content"] if isinstance(item, dict)]
        parsed = [try_json_loads(text) for text in texts if isinstance(text, str)]
        parsed = [item for item in parsed if item is not None]
        if len(parsed) == 1:
            return unwrap_response_payload(parsed[0])
        if parsed:
            return [unwrap_response_payload(item) for item in parsed]
    if isinstance(value, str):
        parsed = try_json_loads(value)
        return unwrap_response_payload(parsed) if parsed is not None else value
    return value


def try_json_loads(value: str) -> Any | None:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def load_optional_response(response_file: str | None) -> Any | None:
    if response_file and response_file != "-":
        with open(response_file, encoding="utf-8") as handle:
            return json.load(handle)
    if response_file == "-" or not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if not raw:
            return None
        return json.loads(raw)
    return None


def load_stdin_json() -> Any:
    raw = sys.stdin.read().strip()
    if not raw:
        raise SystemExit("Expected JSON on stdin")
    return json.loads(raw)


def load_dynatrace_config(environment_alias: str) -> dict[str, str]:
    alias_key = env_key(environment_alias)
    config = {
        "alias": environment_alias,
        "apiEndpointUrl": first_env(f"DT_{alias_key}_URL", f"DT_{alias_key}_API_ENDPOINT_URL") or "",
        "environmentId": first_env(f"DT_{alias_key}_ENVIRONMENT_ID") or "",
        "apiToken": first_env(f"DT_{alias_key}_TOKEN") or "",
    }
    file_config = read_dt_config_file(environment_alias)
    return {**file_config, **{key: value for key, value in config.items() if value}}


def read_dt_config_file(environment_alias: str) -> dict[str, str]:
    for path in candidate_config_paths():
        if not path.exists():
            continue
        entries = parse_simple_dt_config(path.read_text(encoding="utf-8"))
        for entry in entries:
            if entry.get("alias") == environment_alias:
                return resolve_config_env(entry)
    return {}


def candidate_config_paths() -> list[Path]:
    paths = []
    if os.environ.get("DT_CONFIG_FILE"):
        paths.append(Path(os.environ["DT_CONFIG_FILE"]).expanduser())
    current = Path.cwd()
    paths.extend([current / "config" / "dt-config.yaml", current / "dt-config.yaml"])
    for parent in Path(__file__).resolve().parents:
        paths.append(parent / "config" / "dt-config.yaml")
    return paths


def parse_simple_dt_config(content: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            if current:
                entries.append(current)
            current = {}
            line = line[1:].strip()
            if not line:
                continue
        if ":" in line and current is not None:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip().strip("\"'")
    if current:
        entries.append(current)
    return entries


def resolve_config_env(config: dict[str, str]) -> dict[str, str]:
    resolved = dict(config)
    for key, value in list(resolved.items()):
        if value.startswith("${") and value.endswith("}"):
            resolved[key] = os.environ.get(value[2:-1], "")
    return resolved


def metrics_api_base(endpoint: str, environment_id: str | None) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/api/v2"):
        return normalized
    if "/api/v2" in normalized:
        return normalized.split("/api/v2", 1)[0] + "/api/v2"
    if environment_id and f"/e/{environment_id}" not in normalized:
        normalized = f"{normalized}/e/{environment_id}"
    return f"{normalized}/api/v2"


def first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def env_key(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value.upper())


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def escape_selector_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


if __name__ == "__main__":
    raise SystemExit(main())
