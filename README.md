# OpsPilot

OpsPilot composes one DeepAgents runtime per entrypoint. The runtime capability
catalog is declarative and entry-local; credentials never belong in it.

```
config/entries/web.yaml        → Web runtime + Spaces + CopilotKit/AG-UI
config/entries/eval.yaml       → stateless evaluation runtime
config/entries/benchmark.yaml  → isolated AIOpsLab runtime
config/entries/langgraph.yaml  → LangGraph Platform runtime
.env                           → model, database, MCP, sandbox, and tracing secrets
```

The browser owns CopilotKit's frontend tool declarations. The Node bridge only
adapts the Web runtime to CopilotKit; it does not choose models or tools.

## Configure once

```powershell
pnpm install
cd services/agent; uv sync; cd ../..
Copy-Item .env.example .env
```

Choose the DeepAgents harness by editing the relevant file under
`config/entries/`. The `deepagent` subtree follows `create_deep_agent`'s
injection points. For example, the default Web entry is in
[config/entries/web.yaml](config/entries/web.yaml):

```yaml
deepagent:
  model:
    provider: deepseek
    name: deepseek-v4-pro
  tools:
    mcp:
      prometheus:
        url: null
  middleware:
    todo-list: true
  backend:
    type: opensandbox
  checkpointer:
    backend: memory
```

Put only secrets in `.env`:

```dotenv
MODEL_API_KEY=...
DATABASE_URL=...                 # only for a YAML entry using postgres
MCP_BASIC_AUTH_HEADER=...         # only for authenticated MCP endpoints
OPEN_SANDBOX_API_KEY=...          # only for an enabled sandbox
```

## Start the local Web stack

Start the configured OpenSandbox service first:

```powershell
pnpm sandbox:up
```

```powershell
pnpm dev
```

The command reads `config/entries/web.yaml` and starts Vite, FastAPI/AG-UI, and
the CopilotKit bridge with one consistent host, port, agent id, and transport
configuration. Start processes separately only when diagnosing one layer:

```powershell
pnpm run dev:backend
pnpm run dev:copilot
pnpm run dev:web
```

## Run AIOpsLab benchmarks

Bootstrap AIOpsLab once:

```powershell
pnpm benchmark:setup
```

Then edit [config/entries/benchmark.yaml](config/entries/benchmark.yaml):

```yaml
deepagent:
  model:
    provider: deepseek
    name: deepseek-v4-pro
  tools:
    mcp:
      kubernetes:
        kubeconfig: null
  checkpointer:
    backend: none
benchmark:
  aiopslab:
    directory: D:/dev/projects/AIOpsLab
```

`MODEL_API_KEY` remains in `.env`. Run a problem with its fully isolated
runtime:

```powershell
pnpm benchmark:status
pnpm benchmark -- --problem <aiopslab-problem-id> --max-steps 30
pnpm benchmark -- --problem <aiopslab-problem-id> --results-dir ./artifacts/aiopslab
```

The launcher layers the editable AIOpsLab checkout only into this one `uv run`
command, leaving normal Web, eval, and development environments untouched.

## Validate

```powershell
pnpm check
```
