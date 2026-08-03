#!/usr/bin/env python3
"""Discover Dynatrace MongoDB Atlas metric descriptors."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_ENVIRONMENT_ALIAS = "frankfurt"
DEFAULT_FROM = "now-30m"
DEFAULT_TO = "now"
DEFAULT_RESOLUTION = "30m"
DESCRIPTOR_METRIC_SELECTOR = "mongodbatlas.*"
DESCRIPTOR_PAGE_SIZE = "500"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service_name")
    parser.add_argument("--db-name")
    parser.add_argument("--environment-alias", default=DEFAULT_ENVIRONMENT_ALIAS)
    parser.add_argument("--from", dest="from_time", default=DEFAULT_FROM)
    parser.add_argument("--to", dest="to_time", default=DEFAULT_TO)
    parser.add_argument("--resolution", default=DEFAULT_RESOLUTION)
    parser.add_argument(
        "--metric",
        action="append",
        dest="metrics",
        default=[],
        help="Optionally keep only exact metric IDs from the descriptor response.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print query payloads without calling Dynatrace")
    parser.add_argument(
        "--response-file",
        help="Optional metric descriptor/probe response JSON file. Use '-' for stdin.",
    )
    args = parser.parse_args()
    response = load_optional_response(args.response_file)
    if response is not None:
        print_json(parse_metrics(args, response))
    elif args.dry_run:
        print_json(build_discovery_plan(args))
    else:
        print_json(run_direct_discovery(args))
    return 0


def build_discovery_plan(args: argparse.Namespace) -> dict[str, Any]:
    fields = descriptor_fields()
    return {
        "mode": "dry_run",
        "service_name": args.service_name,
        "db_name": args.db_name or args.service_name,
        "environment_alias": args.environment_alias,
        "dynatrace_api_calls": [
            {
                "method": "GET",
                "path": "/api/v2/metrics",
                "arguments": {
                    "metricSelector": DESCRIPTOR_METRIC_SELECTOR,
                    "fields": fields,
                    "pageSize": DESCRIPTOR_PAGE_SIZE,
                },
            }
        ],
        "note": ("Default execution calls Dynatrace metric descriptors directly and follows nextPageKey pagination."),
    }


def run_direct_discovery(args: argparse.Namespace) -> dict[str, Any]:
    """Run descriptor lookup directly against Dynatrace."""

    client = DynatraceClient.from_environment(args.environment_alias)
    return parse_metrics(args, client.list_mongodb_atlas_metrics())


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
        return self.get_json("metrics/query", query, fail_soft=fail_soft, fallback={"result": []})

    def list_mongodb_atlas_metrics(self) -> dict[str, Any]:
        metrics: list[dict[str, Any]] = []
        warnings: list[str] = []
        total_count: int | None = None
        query = {
            "metricSelector": DESCRIPTOR_METRIC_SELECTOR,
            "fields": descriptor_fields(),
            "pageSize": DESCRIPTOR_PAGE_SIZE,
        }

        while True:
            payload = self.get_json(
                "metrics",
                query,
                fail_soft=True,
                fallback={"metrics": []},
            )
            if not isinstance(payload, dict):
                break
            page_metrics = payload.get("metrics")
            if isinstance(page_metrics, list):
                metrics.extend(item for item in page_metrics if isinstance(item, dict))
            page_warnings = payload.get("warnings")
            if isinstance(page_warnings, list):
                warnings.extend(str(item) for item in page_warnings)
            if isinstance(payload.get("totalCount"), int):
                total_count = payload["totalCount"]

            next_page_key = payload.get("nextPageKey")
            if not next_page_key:
                break
            query = {"nextPageKey": str(next_page_key)}

        return {
            "metricSelector": DESCRIPTOR_METRIC_SELECTOR,
            "metrics": metrics,
            "totalCount": total_count if total_count is not None else len(metrics),
            "warnings": sorted(set(warnings)),
        }

    def get_json(
        self,
        path: str,
        query: dict[str, str],
        *,
        fail_soft: bool,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path}?{urllib.parse.urlencode(query)}"
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
                raise SystemExit(f"Dynatrace request failed ({exc.code}): {body}") from exc
            result = dict(fallback)
            result.setdefault("warnings", []).append(f"{exc.code}: {body}")
            return result
        except urllib.error.URLError as exc:
            if not fail_soft:
                raise SystemExit(f"Dynatrace request failed: {exc.reason}") from exc
            result = dict(fallback)
            result.setdefault("warnings", []).append(str(exc.reason))
            return result


def parse_metrics(args: argparse.Namespace, raw_payload: Any) -> dict[str, Any]:
    payload = unwrap_response_payload(raw_payload)
    descriptors = collect_descriptors(payload)
    query_metrics = collect_query_metrics(payload)
    merged = merge_metric_sources(descriptors, query_metrics)
    if args.metrics:
        selected = set(args.metrics)
        merged = {metric_id: metric for metric_id, metric in merged.items() if metric_id in selected}
    categories = defaultdict(list)
    for metric in sorted(merged.values(), key=lambda item: item["metricId"]):
        categories[categorize_metric(metric["metricId"])].append(metric)
    return {
        "service_name": args.service_name,
        "db_name": args.db_name or args.service_name,
        "environment_alias": args.environment_alias,
        "timeframe": {"from": args.from_time, "to": args.to_time},
        "metric_selector": DESCRIPTOR_METRIC_SELECTOR,
        "descriptor_total_count": descriptor_total_count(payload),
        "metric_count": len(merged),
        "categories": dict(sorted(categories.items())),
        "warnings": collect_warnings(payload),
    }


def collect_descriptors(payload: Any) -> dict[str, dict[str, Any]]:
    descriptors: dict[str, dict[str, Any]] = {}
    for candidate in iter_dicts(payload):
        raw_metric_id = candidate.get("metricId")
        if not isinstance(raw_metric_id, str) or "mongodbatlas" not in raw_metric_id.lower():
            continue
        if "data" in candidate and "dimensionDefinitions" not in candidate:
            continue
        metric_id = normalize_mongodb_atlas_metric_id(raw_metric_id)
        descriptors[metric_id] = {
            "metricId": metric_id,
            "rawMetricId": raw_metric_id if raw_metric_id != metric_id else None,
            "displayName": candidate.get("displayName"),
            "description": candidate.get("description"),
            "unit": candidate.get("unit"),
            "entityType": candidate.get("entityType"),
            "metricValueType": candidate.get("metricValueType"),
            "aggregationTypes": candidate.get("aggregationTypes"),
            "defaultAggregation": candidate.get("defaultAggregation"),
            "dimensions": extract_descriptor_dimensions(candidate),
            "transformations": candidate.get("transformations"),
            "lastWritten": candidate.get("lastWritten"),
            "source": "descriptor",
            "hasData": None,
            "warnings": [],
        }
    return descriptors


def collect_query_metrics(payload: Any) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for metric in iter_metric_results(payload):
        metric_id = str(metric.get("metricId") or "")
        base_metric_id = normalize_mongodb_atlas_metric_id(metric_id)
        if "mongodbatlas" not in base_metric_id.lower():
            continue
        data = metric.get("data") if isinstance(metric.get("data"), list) else []
        metrics[base_metric_id] = {
            "metricId": base_metric_id,
            "rawMetricId": metric_id if metric_id != base_metric_id else None,
            "displayName": None,
            "description": None,
            "unit": None,
            "entityType": None,
            "metricValueType": None,
            "aggregationTypes": None,
            "defaultAggregation": None,
            "dimensions": extract_query_dimensions(metric),
            "transformations": None,
            "lastWritten": None,
            "source": "query_probe",
            "hasData": any(has_numeric_values(series) for series in data),
            "seriesCount": len(data),
            "warnings": metric.get("warnings") or [],
        }
    return metrics


def merge_metric_sources(
    descriptors: dict[str, dict[str, Any]], query_metrics: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    merged = dict(query_metrics)
    for metric_id, descriptor in descriptors.items():
        if metric_id in merged:
            has_data = merged[metric_id].get("hasData")
            warnings = merged[metric_id].get("warnings") or []
            descriptor = dict(descriptor)
            descriptor["hasData"] = has_data
            descriptor["warnings"] = warnings
        merged[metric_id] = descriptor
    return merged


def extract_descriptor_dimensions(metric: dict[str, Any]) -> list[str]:
    dimensions = metric.get("dimensionDefinitions")
    if not isinstance(dimensions, list):
        return []
    result = []
    for dimension in dimensions:
        if isinstance(dimension, dict):
            key = dimension.get("key") or dimension.get("name") or dimension.get("displayName")
            if key:
                result.append(str(key))
    return result


def extract_query_dimensions(metric: dict[str, Any]) -> list[str]:
    dimensions: set[str] = set()
    for series in metric.get("data") or []:
        dimension_map = series.get("dimensionMap")
        if isinstance(dimension_map, dict):
            dimensions.update(str(key) for key in dimension_map)
    return sorted(dimensions)


def collect_warnings(payload: Any) -> list[str]:
    warnings: list[str] = []
    for candidate in iter_dicts(payload):
        value = candidate.get("warnings")
        if isinstance(value, list):
            warnings.extend(str(item) for item in value)
    return sorted(set(warnings))


def descriptor_total_count(payload: Any) -> int | None:
    for candidate in iter_dicts(payload):
        total_count = candidate.get("totalCount")
        if isinstance(total_count, int):
            return total_count
    return None


def descriptor_fields() -> str:
    return ",".join(
        [
            "displayName",
            "description",
            "unit",
            "entityType",
            "metricValueType",
            "aggregationTypes",
            "defaultAggregation",
            "dimensionDefinitions",
            "transformations",
            "lastWritten",
        ]
    )


def normalize_mongodb_atlas_metric_id(metric_id: str) -> str:
    if metric_id.startswith("mongodbatlas."):
        return metric_id.split(":", 1)[0]
    return metric_id


def categorize_metric(metric_id: str) -> str:
    lowered = metric_id.lower()
    if ".db." in lowered:
        return "database"
    if "replication" in lowered or "oplog" in lowered or "replica" in lowered:
        return "replication"
    if "connection" in lowered:
        return "connections"
    if "opcounters" in lowered or "operation" in lowered:
        return "operations"
    if any(token in lowered for token in ("cpu", "memory", "disk", "network", "paging")):
        return "resource"
    if "host" in lowered or "process" in lowered:
        return "host_process"
    return "unknown"


def iter_metric_results(payload: Any) -> list[dict[str, Any]]:
    payload = unwrap_response_payload(payload)
    if isinstance(payload, dict) and isinstance(payload.get("result"), list):
        return [item for item in payload["result"] if isinstance(item, dict)]
    if isinstance(payload, dict) and "metricId" in payload and "data" in payload:
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


def iter_dicts(payload: Any) -> list[dict[str, Any]]:
    payload = unwrap_response_payload(payload)
    found: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        found.append(payload)
        for value in payload.values():
            found.extend(iter_dicts(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(iter_dicts(item))
    return found


def has_numeric_values(series: dict[str, Any]) -> bool:
    values = series.get("values")
    return isinstance(values, list) and any(isinstance(value, (int, float)) for value in values)


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
