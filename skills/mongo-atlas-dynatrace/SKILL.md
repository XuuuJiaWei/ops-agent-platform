---
name: mongo-atlas-dynatrace
description: Discover MongoDB Atlas hosts, replica roles, and available metrics for a service/database using Dynatrace Metrics API credentials from the environment.
---

# MongoDB Atlas Discovery Through Dynatrace

Use this skill when the user asks for MongoDB Atlas host lists, primary/secondary role relationships, or available MongoDB Atlas metrics for a service name.

This skill provides local helper scripts that call Dynatrace Metrics API v2 directly. The scripts read Dynatrace endpoint metadata from `DT_CONFIG_FILE` or `config/dt-config.yaml`, and read the API token from `DT_<ENVIRONMENT_ALIAS>_TOKEN` such as `DT_FRANKFURT_TOKEN`.

## Grounding

- Dynatrace Metrics API v2 queries use `metricSelector`, optional `entitySelector`, `from`, `to`, and `resolution`. The response contains `result[].metricId`, `result[].data[]`, `dimensionMap`, timestamps, and values.
- Dynatrace metric descriptors list available metrics with fields such as `metricId`, `displayName`, `unit`, `aggregationTypes`, `defaultAggregation`, `dimensionDefinitions`, `transformations`, and `lastWritten`.
- MongoDB Atlas monitoring exposes host and replication metrics. Replica sets have primary/secondary roles; Atlas replication lag and oplog metrics are useful evidence for secondary nodes, while a node missing from secondary-only replication-lag series can be a primary candidate.

## Default Assumptions

- Treat the service name as `mongodb_atlas.db.name` unless the user gives a separate database name.
- Use `environment_alias="frankfurt"` unless the user specifies another Dynatrace environment alias.
- Use `from="now-30m"`, `to="now"`, and `resolution="30m"` for quick discovery.
- The primary host query is:

```json
{
  "metricSelector": "mongodbatlas.db.counts:filter(eq(\"mongodb_atlas.db.name\",\"case\")):splitBy(\"mongodb_atlas.db.name\",\"mongodb_atlas.host.name\")",
  "from": "now-30m",
  "to": "now",
  "resolution": "30m",
  "environment_alias": "frankfurt"
}
```

## Workflow: Host List And Roles

Run the host discovery CLI from this skill directory. Pass only the service/database name and the Dynatrace environment alias unless the user gives a different database name or timeframe. The script performs all Dynatrace API calls and returns normalized JSON.

```bash
python scripts/discover_mongo_hosts.py <service-name> --environment-alias frankfurt
```

If the database name differs from the service name, add `--db-name <atlas-db-name>`.
Use `--dry-run` only when you need to inspect the generated Dynatrace API metric selectors without calling Dynatrace.

Report role confidence clearly. If role evidence is only inferred from replication metrics, say `primary_candidate` or `secondary_candidate`, not guaranteed primary/secondary.

## Workflow: Available Metrics

Run the metrics discovery CLI from this skill directory:

```bash
python scripts/discover_mongo_metrics.py <service-name> --environment-alias frankfurt
```

The script calls Dynatrace `GET /api/v2/metrics` with `metricSelector=mongodbatlas.*`, follows `nextPageKey` pagination, and returns the grouped descriptor list. Use `--dry-run` only to inspect the generated Dynatrace API descriptor request.

When reporting available metrics, include the metric ID, display name if present, dimensions, aggregations if present, `lastWritten` if present, and any Dynatrace warnings.

## Output Style

- Start with the discovered host list and role relationship.
- Then list available metrics grouped by category: database, host/process, replication, connections, operations, resource, and unknown.
- Always include the Dynatrace environment alias and timeframe used.
- Mention when `mongodb_atlas.db.name` was assumed from the service name.
- Do not expose tokens or local config content.
