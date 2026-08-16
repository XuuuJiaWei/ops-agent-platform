# OpsPilot

[![CI](https://github.com/XuuuJiaWei/ops-agent-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/XuuuJiaWei/ops-agent-platform/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**OpsPilot is a tool-using incident-localization agent evaluated on Microsoft AIOpsLab.**

AIOpsLab owns the reproducible cloud environment, workload, injected fault, ground truth, and task evaluator. OpsPilot owns the agent runtime: it investigates the same cluster through configured Kubernetes and observability MCP tools, submits a structured localization result, and records runtime behavior separately from task quality.

```text
AIOpsLab
  deploy app -> inject fault -> start workload
                         |
                         v
                    OpsPilot
             Kubernetes / metrics / traces
                         |
                         v
              submit_localization([...])
                         |
                         v
              AIOpsLab task evaluator
```

This split is intentional: **AIOpsLab answers whether the agent solved the incident; runtime tests answer whether execution stayed bounded and recoverable.**

## Benchmark

The first supported benchmark slice is **fault localization**. The bridge is a thin wrapper around AIOpsLab's official `Orchestrator`, `Session`, problem lifecycle, and evaluator; it runs in the AIOpsLab environment so AIOpsLab does not become a dependency of the production Agent service.

Run the bridge from an AIOpsLab checkout/environment:

```bash
python /path/to/ops-agent-platform/benchmarks/aiopslab_bridge/app.py
```

Then run OpsPilot against one AIOpsLab problem:

```bash
cd services/agent
uv run ops_pilot benchmark \
  --base-url http://127.0.0.1:1819 \
  --problem astronomy_shop_payment_service_failure-localization-1
```

The benchmark path deliberately does not reuse AIOpsLab's built-in agent actions. OpsPilot continues to use its own configured MCP tools, so the evaluation measures the actual runtime and tool surface used by the project.

Example result shape:

```json
{
  "problem_id": "astronomy_shop_payment_service_failure-localization-1",
  "solution": ["payment"],
  "task_metrics": {
    "Localization Accuracy": 100.0,
    "success": true
  },
  "runtime_metrics": {
    "tool_calls": 6,
    "steps": 14,
    "latency_s": 31.2
  }
}
```

The numbers above illustrate the output schema only; benchmark claims should use results from real runs.

### Non-flag faults and observation isolation

AIOpsLab's built-in Astronomy Shop problems toggle OpenTelemetry demo feature
flags, so an agent with kubectl access can read the `flagd-config` ConfigMap
and read the fault off the flag. That couples the fault injection surface with
the agent's observation surface and does not resemble a real incident.

This bridge registers an additional set of problems that keep the same
Astronomy Shop workload but inject faults through Chaos Mesh (pod failure,
network loss) selected by the demo's own labels:

```bash
uv run ops_pilot benchmark \
  --base-url http://127.0.0.1:1819 \
  --problem astronomy_shop_payment_pod_kill-localization-1
```

Available custom problems are `astronomy_shop_payment_pod_kill-localization-1`
and `astronomy_shop_payment_network_loss-localization-1`. The agent can only
observe the effects (restarts, latency, error rates), never the injection.

Because these Chaos faults never modify the application itself, the bridge
keeps a warm deployment across runs by default (`AIOPSLAB_PERSISTENT=0` forces
the official delete/redeploy lifecycle). The first run deploys OpenEBS,
Prometheus, and the app chart (~5 minutes); every later run only checks health,
injects the fault, and recovers it (~1 minute). The app stays deployed between
runs, so a full benchmark cycle is dominated by the agent's investigation
instead of environment setup.

The mode is switchable per run without restarting the bridge: pass
`"persistent": false` in the `POST /runs` body for a one-shot lifecycle, or use
the CLI flags:

```bash
uv run ops_pilot benchmark --problem astronomy_shop_payment_pod_kill-localization-1 --persistent
uv run ops_pilot benchmark --problem astronomy_shop_payment_pod_kill-localization-1 --no-persistent
```

The observer identity for the agent's Kubernetes MCP tools is a read-only,
namespace-scoped Role that deliberately excludes configmaps, secrets, exec,
and write verbs:

```bash
kubectl apply -f benchmarks/aiopslab_bridge/rbac/observer.yaml
powershell -File benchmarks/aiopslab_bridge/rbac/create-observer-kubeconfig.ps1
```

The bridge re-applies the Role/RoleBinding after every run because the app
namespace is torn down and recreated; the ServiceAccount lives in the stable
`ops-pilot` namespace so its token survives runs. Point the Kubernetes MCP
server at the generated `ops-pilot-observer.kubeconfig` (token valid 24h by
default).

On managed clusters whose kubeconfig uses an exec credential plugin (for
example Gardener's `gardenlogin`), the Kubernetes Python client used by
AIOpsLab cannot resolve the plugin. Start the bridge with `KUBECONFIG` pointing
at a static admin kubeconfig (ServiceAccount token) instead; that is also the
injection-plane credential, kept separate from the agent's observer identity:

```powershell
$env:KUBECONFIG = "D:\dev\projects\AIOpsLab\aiopslab-admin.kubeconfig"
uv run python benchmarks/aiopslab_bridge/app.py
```

## Runtime

OpsPilot builds one DeepAgents runtime over the configured model and MCP tools. Production guardrails prefer official framework primitives over custom control logic:

- LangChain `ModelCallLimitMiddleware` and `ToolCallLimitMiddleware` bound agent loops.
- LangChain `ToolRetryMiddleware` is applied only to explicitly retry-safe tools.
- DeepAgents/LangGraph provide the agent loop and checkpoint integration.
- PostgreSQL can back durable LangGraph checkpoints.
- Configured high-risk MCP tools require human approval.
- Optional sandboxing isolates filesystem and command execution.
- `RunController` owns the outer run deadline and cooperative cancellation boundary.

The runtime does **not** claim exactly-once execution across external systems. A checkpoint cannot prove whether an external side effect succeeded after a response was lost; downstream business idempotency and reconciliation remain downstream responsibilities.

## Tool configuration

Regular configuration lives in `config/config.yaml` (copy `config/config.example.yaml`). Secrets stay in `.env`.

The benchmark environment is not configured here. This file only describes the Agent's own tool surface and runtime policy. A typical localization setup enables Kubernetes plus read-only metrics/tracing tools that can reach the AIOpsLab-managed cluster.

```bash
cp .env.example .env
cp config/config.example.yaml config/config.yaml
```

## Local development

Install dependencies:

```bash
pnpm install
cd services/agent && uv sync
```

Start the interactive product stack:

```bash
pnpm dev
```

The web UI and protocol adapters are secondary interfaces over the same backend runtime: CopilotKit/AG-UI serve human interaction, and the A2A endpoint serves programmatic clients. They do not own agent policy or benchmark logic.

## Validation

Runtime correctness is tested independently from live AIOpsLab task quality:

```bash
cd services/agent
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest
```

Smoke checks:

```bash
pnpm run smoke:model
pnpm run smoke:agent
pnpm run smoke:a2a
pnpm run smoke:local
```

The secret-free checks also run in GitHub Actions.

## Project boundary

OpsPilot intentionally does not implement its own cloud fault benchmark, feature-flag chaos controller, benchmark dataset registry, or AIOps ground-truth graders. Those concerns belong to AIOpsLab. The repository focuses on the Agent runtime and a small adapter needed to evaluate that runtime against an external benchmark.

This is an independent personal engineering project, not an SAP product, Microsoft product, or official implementation from any dependency vendor.

## License

Licensed under the [MIT License](LICENSE).
