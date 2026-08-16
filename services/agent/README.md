# OpsPilot agent service

The agent package exposes a host-neutral `build_agent_runtime(RuntimeSpec)`.
It never loads a global YAML file or picks a default model, MCP server, or host
extension.

Runtime combinations live in `ops_pilot.entrypoints`:

- `web.py` owns the AG-UI/A2A web surface and opts into Spaces and the
  CopilotKit middleware.
- `eval.py` owns the stateless evaluation surface.
- `benchmark.py` owns the AIOpsLab surface and intentionally excludes web
  extensions.
- `langgraph.py` owns the LangGraph Platform surface.

Each entry reads only environment variables with its own prefix. For example,
`OPS_PILOT_WEB_*` cannot alter the benchmark runtime, and
`OPS_PILOT_BENCHMARK_*` cannot alter the web runtime.

```bash
uv run ops_pilot profiles
uv run ops_pilot serve
uv run ops_pilot status --entry benchmark
uv run ops_pilot benchmark --problem <problem-id>
```

For normal use, run benchmarks from the repository root instead:

```bash
pnpm benchmark:setup
pnpm benchmark -- --problem <problem-id> --max-steps 30
```

The root launcher requires `OPS_PILOT_AIOPSLAB_DIR` and layers that editable
AIOpsLab checkout over this project only for the benchmark process. Configure
the benchmark runtime with `OPS_PILOT_BENCHMARK_*`; see the root `.env.example`
for the full model, MCP, and optional persistence settings.

The core runtime accepts model, MCP catalog, tools, middleware, sandbox,
checkpointer, tracing, and lifecycle configuration from the entry-owned
`RuntimeSpec`, matching DeepAgents' application-supplied composition model.
