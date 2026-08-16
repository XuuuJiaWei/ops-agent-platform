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

## Configure and run the web application

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

Install once:

```bash
pnpm install
cd services/agent && uv sync
cd ../..
copy .env.example .env
copy apps/web/.env.example apps/web/.env
copy apps/copilot-runtime/.env.example apps/copilot-runtime/.env
```

Set the Web entry's model and optional MCP catalog in the repository `.env`.
For example:

```dotenv
OPS_PILOT_WEB_MODEL_PROVIDER=openai
OPS_PILOT_WEB_MODEL_NAME=gpt-4.1
MODEL_API_KEY=...
```

Start the complete local application:

```bash
# Vite: http://127.0.0.1:3000
# FastAPI/AG-UI: http://127.0.0.1:8123
# CopilotKit bridge: http://127.0.0.1:4001
pnpm dev

# Or start one process at a time.
pnpm run dev:backend
pnpm run dev:copilot
pnpm run dev:web
```

`scripts/dev.mjs` reads the repository `.env` before deriving the three
processes' host, port, agent id, and bridge URL. Override the defaults with
`OPS_PILOT_WEB_HOST`, `OPS_PILOT_WEB_PORT`, and
`OPS_PILOT_WEB_CHAT_BASE_PATH` in that file.

## Run AIOpsLab benchmarks

Bootstrap AIOpsLab once. The setup script clones the official repository with
submodules, writes its `aiopslab/config.yml`, and verifies it as an ephemeral
editable dependency; it does not alter the OpsPilot virtual environment.

```powershell
pnpm benchmark:setup
```

Then add this isolated benchmark configuration to the repository `.env`:

```dotenv
OPS_PILOT_AIOPSLAB_DIR=D:/dev/projects/AIOpsLab
OPS_PILOT_BENCHMARK_MODEL_PROVIDER=openai
OPS_PILOT_BENCHMARK_MODEL_NAME=gpt-4.1
MODEL_API_KEY=...

# Optional: allow the benchmark runtime's explicit Kubernetes MCP declaration.
OPS_PILOT_BENCHMARK_KUBECONFIG=C:/Users/you/.kube/config
```

Run a problem from the root:

```bash
pnpm benchmark:status
pnpm benchmark -- --problem <aiopslab-problem-id> --max-steps 30
pnpm benchmark -- --problem <aiopslab-problem-id> --results-dir ./artifacts/aiopslab
```

The launcher uses `uv run --with-editable` for that one command, so the
benchmark package and its dependencies remain separate from normal Web, eval,
and development runtime environments.

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
