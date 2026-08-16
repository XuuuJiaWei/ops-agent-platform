# OpsPilot

OpsPilot is an operations agent platform built around explicitly composed
DeepAgents runtimes. There is no process-wide agent configuration: each host
declares the model, MCP catalog, tools, policies, persistence, sandbox, and
extensions it needs.

```
web entry          → web RuntimeSpec + Spaces + CopilotKit/AG-UI adapter
eval entry         → eval RuntimeSpec only
benchmark entry    → AIOpsLab RuntimeSpec only
LangGraph entry    → LangGraph RuntimeSpec only
```

The browser owns its CopilotKit declaration and frontend tools. The Node
CopilotKit service is a protocol/event-journal adapter only; it does not select
the business agent runtime. Backend-only credentials and MCP process details
never reach the browser.

## Configure an entry

Secrets and deployment values live in `.env` (copy `.env.example`). Runtime
choices use entry-specific environment variables, for example:

```dotenv
OPS_PILOT_WEB_MODEL_PROVIDER=openai
OPS_PILOT_WEB_MODEL_NAME=gpt-4.1
OPS_PILOT_WEB_KUBECONFIG=C:/Users/you/.kube/config
OPS_PILOT_BENCHMARK_MODEL_PROVIDER=openai
OPS_PILOT_BENCHMARK_MODEL_NAME=gpt-4.1
OPS_PILOT_BENCHMARK_PROMETHEUS_MCP_URL=https://prometheus.example/mcp
MODEL_API_KEY=...
```

Inspect the declared combinations without initializing a model:

```bash
cd services/agent
uv run ops_pilot profiles
```

## Run

```bash
pnpm install
cd services/agent && uv sync

# web, backend and CopilotKit protocol adapter
pnpm dev

# one entrypoint at a time
pnpm run dev:web
pnpm run dev:backend
pnpm run dev:copilot

# the isolated benchmark composition
cd services/agent
uv run ops_pilot benchmark --problem <aiopslab-problem-id>
```

## Validate

```bash
pnpm lint
pnpm run format:check
pnpm typecheck
pnpm test
```

MCP transport behavior follows the official LangChain MCP adapter; runtime
guardrails use DeepAgents/LangChain primitives; client tools use CopilotKit v2
`useFrontendTool`. See the entrypoint modules under
`services/agent/src/ops_pilot/entrypoints` for the concrete compositions.
