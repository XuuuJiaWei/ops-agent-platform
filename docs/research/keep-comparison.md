# Keep vs ops_pilot Comparison

Date: 2026-08-06

## Sources

- Keep README: https://github.com/keephq/keep/blob/main/README.md
- Keep architecture docs: https://github.com/keephq/keep/blob/main/docs/deployment/kubernetes/architecture.mdx
- Keep alert management docs: https://github.com/keephq/keep/blob/main/docs/alerts/overview.mdx
- Keep incident docs: https://github.com/keephq/keep/blob/main/docs/incidents/overview.mdx
- Keep workflows docs: https://github.com/keephq/keep/blob/main/docs/workflows/overview.mdx
- Keep provider provisioning docs: https://github.com/keephq/keep/blob/main/docs/deployment/provision/provider.mdx
- Keep workflow provisioning docs: https://github.com/keephq/keep/blob/main/docs/deployment/provision/workflow.mdx
- Keep AI correlation docs: https://github.com/keephq/keep/blob/main/docs/overview/ai-correlation.mdx
- Keep semi-automatic AI correlation docs: https://github.com/keephq/keep/blob/main/docs/overview/ai-semi-automatic-correlation.mdx
- Keep AI in workflows docs: https://github.com/keephq/keep/blob/main/docs/overview/ai-in-workflows.mdx
- Keep AI workflow builder docs: https://github.com/keephq/keep/blob/main/docs/overview/ai-workflow-assistant.mdx
- Keep provider base class: https://github.com/keephq/keep/blob/main/keep/providers/base/base_provider.py
- Keep alert and incident DTOs: https://github.com/keephq/keep/blob/main/keep/api/models/alert.py and https://github.com/keephq/keep/blob/main/keep/api/models/incident.py
- Local ops_pilot README: ../../README.md
- Local sandbox manager: ../../services/agent/src/ops_pilot/sandbox/manager.py
- Local runtime assembly: ../../services/agent/src/ops_pilot/agent/runtime.py
- Local correlation contract: ../../services/agent/src/ops_pilot/correlation/models.py and ../../apps/web/src/app/storyline.ts

## Summary

Keep is a complete AIOps and alert-management platform: alert ingestion, deduplication, enrichment, filtering, correlation, incident management, workflows, dashboards, provider provisioning, websocket updates, persistent storage, and deployment packaging. Its AI features are layered onto a structured alert/incident/workflow product.

ops_pilot is currently an agent-first operations assistant: DeepAgents runtime, SAP AI Core model integration, MCP tools, sandboxed execution, CopilotKit chat, AG-UI, A2A, Langfuse tracing, and a developing multi-source storyline/correlation surface. Its strongest asset is controlled agent execution over enterprise tools; its weaker area compared with Keep is persistent alert/incident/workflow system-of-record functionality.

## Main Differences

### Product Boundary

Keep owns the operational data model. It has first-class alerts, incidents, correlation rules, workflows, providers, dashboards, maintenance windows, presets/facets, topology, and APIs for those resources.

ops_pilot owns an agent runtime and protocol surface. It can reason over tools and produce a storyline, but it does not yet persist alerts/incidents/workflows as core product entities.

### Integration Model

Keep has a large provider catalog, with provider metadata, categories, scopes, methods, authentication, optional webhook installation, provisioning, and provider-specific alert normalization. A shallow clone showed 134 `*provider*.py` files under `keep/providers`.

ops_pilot currently integrates primarily through MCP servers configured in `config/config.yaml`, plus a correlation tool over Dynatrace/Kibana-style MCP tools. This is flexible for agents but less structured for alert ingestion, provider lifecycle, and provider health.

### Workflow Model

Keep workflows are declarative YAML with metadata, triggers, steps/actions, providers, conditions, functions, context, foreach loops, and alert enrichment. Workflows can be provisioned from a directory and reloaded on restart.

ops_pilot does not yet have a first-class declarative automation DSL. It has DeepAgents tools, HITL tool configuration, and sandbox execution. That is good for exploratory operations, but weaker for repeatable, auditable runbooks.

### AI Placement

Keep places AI inside a structured operations product: AI correlation, semi-automatic incident creation, AI incident assistant, AI workflow builder, and AI providers as workflow steps/actions.

ops_pilot places AI at the center: the agent is the primary interface and orchestration layer. This is more flexible and conversational, but currently has less product scaffolding around review, persistence, audit, and deterministic automation.

### UI Shape

Keep's UI is an operational workbench: alert table, facets, presets, incidents, topology, workflows, dashboards, and real-time websocket updates.

ops_pilot's UI is intentionally thin: CopilotKit chat plus agent-native panels such as the storyline view. This is simpler and fits assistant workflows, but not yet dense enough for repeated alert triage.

### Runtime And Deployment

Keep ships a multi-service deployment: frontend, FastAPI backend, websocket server, and database. It supports SQLite/PostgreSQL/MySQL/SQL Server and has Kubernetes/Helm-style deployment guidance.

ops_pilot ships a local dev stack with Vite web, Copilot runtime, and FastAPI backend. The backend owns MCP sessions and sandbox lifecycle; persistence is not yet an AIOps product database.

## What ops_pilot Can Absorb Immediately

1. Define persistent alert and incident DTOs.
   Start with a small local model inspired by Keep: `Alert`, `Incident`, `IncidentAlertLink`, severity/status enums, source/provider fields, fingerprint, labels, service, environment, timestamps, assignee, generated summary, and correlation type. This gives the agent something durable to operate on.

2. Add provider metadata around MCP tools.
   Keep's provider model separates provider type, provider id, auth/config, categories/tags, scopes, and capabilities. ops_pilot can add a `ProviderRegistry` facade over configured MCP servers without replacing MCP: Dynatrace and Kibana become providers with declared capabilities such as `alerts`, `logs`, `metrics`, `topology`, `actions`.

3. Add alert normalization and fingerprinting.
   Keep normalizes alerts into a common DTO and assigns fingerprints for deduplication. ops_pilot can normalize Dynatrace/Kibana findings into a shared `Signal`/`Alert` model before sending them to the storyline generator.

4. Add rule-based correlation before more AI.
   Keep's manual correlation rules are deterministic and explainable. ops_pilot can add simple rules over normalized signals: group by service/entity/deployment/window/severity, name incidents by template, and mark rule vs AI correlation.

5. Turn the existing storyline into an incident candidate.
   The current `Storyline` contract already has nodes, root cause, narrative, confidence, gaps, and timestamps. Add persistence and review states: `candidate`, `accepted`, `rejected`, `merged`. That would turn the panel from a transient explanation into an AIOps workflow object.

6. Add declarative runbook/workflow YAML.
   Keep workflows are a strong pattern: triggers, steps, actions, providers, conditions, context, foreach, enrichment. ops_pilot can start smaller: manual trigger only, MCP tool step, sandbox step, condition, and HITL approval. DeepAgents can then help author or execute these workflows.

7. Add provisioning directories.
   Keep supports provider/workflow provisioning from directories. ops_pilot already has config-driven MCP and skills. Add `config/providers/` and `config/workflows/` directories for repeatable local/company setup.

8. Add dense alert/incident table views.
   Keep's single pane of glass is a table/facet/preset experience, not only chat. ops_pilot can add a compact incident candidate table backed by normalized signals and storyline records while preserving CopilotKit chat.

9. Add websocket/shared-state update discipline.
   Keep uses websocket infrastructure for real-time updates. ops_pilot already has CopilotKit shared state. Standardize event/state updates for storyline, tool progress, incident candidates, and workflow runs.

10. Add audit/run history for agent and workflow actions.
   Keep's product model records workflow runs and incident activity. ops_pilot should persist agent tool calls, MCP action results, sandbox command summaries, approvals, and generated recommendations as auditable events.

## Suggested Adoption Order

1. Normalized signal/alert model plus fingerprinting.
2. Incident candidate persistence built from the current storyline output.
3. Provider metadata facade over MCP servers.
4. Rule-based correlation and incident naming templates.
5. Minimal declarative workflow/runbook YAML with HITL.
6. Dense incident/alert table in the frontend.

This order preserves ops_pilot's agent-first advantage while borrowing Keep's durable AIOps product spine.
