# DeepAgent SAP AI Core Chat Requirements

Date: 2026-07-31

## 1. Goal

Build a local-first AI agent application, managed with `uv` for Python 3.12 and `pnpm` for the frontend, that runs a LangChain DeepAgent backed by SAP AI Core / SAP Generative AI Hub models.

The system must expose the same DeepAgent through two protocol surfaces:

- [ ] `/chat/*`: a DeepAgents/LangGraph-compatible frontend protocol base path that works with the official `@langchain/react` `useStream` SDK without a custom transport.
- [ ] `/a2a/*`: a Google open-source Agent2Agent (A2A) protocol surface implemented with the official A2A Python SDK or official server components.

The agent must support deployment-level MCP tools, local-path DeepAgents skills, runtime thread/run/task/checkpoint state, and Langfuse tracing. The first version is local development only; deployment to LangSmith/LangGraph Cloud is not in scope.

The agent should follow DeepAgents official defaults wherever possible, with one explicit exception: **do not configure DeepAgents long-term/semantic memory**. In this requirement document, "memory" means DeepAgents memory configuration such as `memory=` and AGENTS.md memory loading. Runtime state for thread continuity, run resume, interrupts, A2A task mapping, and checkpointing remains required.

Sources: [DeepAgents customization](https://docs.langchain.com/oss/python/deepagents/customization), [DeepAgents frontend overview](https://docs.langchain.com/oss/python/deepagents/frontend/overview), [LangGraph local server API](https://docs.langchain.com/oss/python/langgraph/local-server), [A2A protocol definitions](https://a2a-protocol.org/latest/definitions)

## 2. Technical Baseline

- [ ] Backend runtime: Python `3.12`.
- [ ] Backend package manager: `uv`.
- [ ] Frontend package manager: `pnpm`.
- [ ] Frontend framework: Vite + React + Tailwind.
- [ ] Frontend SDK: official `@langchain/react` `useStream`.
- [ ] Local dev orchestration: `pnpm` scripts + a cross-platform Node process supervisor.
- [ ] Agent runtime: LangChain DeepAgents / LangGraph-compatible graph.
- [ ] Model provider: SAP AI Core via SAP Cloud SDK for AI / `sap-ai-sdk-gen` LangChain integration.
- [ ] Primary SAP model initialization path: `gen_ai_hub.proxy.langchain.init_llm(model_name=...)`.
- [ ] A2A implementation path: official Google/A2A Python SDK `a2a-sdk[http-server]>=1.1.2,<2`, with the exact resolved version locked through `uv.lock`.
- [ ] Observability: Langfuse tracing through LangChain/LangGraph callback integration.
- [ ] SDK and framework top-level dependencies should use conservative major-version ranges in `pyproject.toml` / `package.json`, with exact reproducibility provided by `uv.lock` and `pnpm-lock.yaml`.

Python 3.12 satisfies the current DeepAgents Python 3.11+ requirement identified in prior research. The first implementation should use the narrowest SAP SDK dependency set that supports `init_llm(model_name=...)` and the configured model; do not use `sap-ai-sdk-gen[all]` unless a selected model path requires it, because broad extras increase dependency conflict risk. [SAP integration research](../research/deepagents-sap-ai-sdk-integration.md)

## 3. Scope

### In Scope

- [ ] DeepAgent backend service for local development.
- [ ] SAP AI Core model initialization through SAP SDK LangChain integration.
- [ ] Official DeepAgents default behavior, excluding configured long-term/semantic memory.
- [ ] Runtime thread/run/task/checkpoint state required for conversation continuity and protocol correctness.
- [ ] Deployment-level MCP server configuration and tool loading.
- [ ] Local-path DeepAgents skills configuration.
- [ ] Default DeepAgents general-purpose subagent behavior, with future custom subagent configuration space.
- [ ] Langfuse trace recording for `/chat` and `/a2a` agent runs.
- [ ] `/chat/*` base path compatible with official `@langchain/react useStream`.
- [ ] `/a2a/*` base path compatible with Google open-source Agent2Agent protocol.
- [ ] Vite + React + Tailwind frontend with chat panel, thread history list/cache, and streaming output.
- [ ] One-command local development workflow.
- [ ] Environment-based configuration for secrets and local ports.

### Out of Scope for First Version

- [ ] DeepAgents long-term/semantic memory or AGENTS.md memory loading.
- [ ] Deployment to LangSmith/LangGraph Cloud.
- [ ] Production persistence for A2A tasks across process restarts.
- [ ] User authentication, SAP SSO, and RBAC for local development.
- [ ] Runtime/user-level MCP configuration.
- [ ] Remote skills registry or runtime skill upload.
- [ ] Custom DeepAgents subagent definitions as a required first-version feature.
- [ ] Full agent-native ops dashboard panels beyond structural extension points.
- [ ] Custom SAP domain tools beyond MCP-loaded tools and initial smoke-test tools.

## 4. Functional Requirements

### FR-1: Project and Runtime Setup

- [ ] The backend must be initialized as a `uv` Python 3.12 project.
- [ ] The backend must define dependencies in `pyproject.toml` and lock them with `uv.lock`.
- [ ] The frontend must be initialized as a `pnpm` project using Vite, React, and Tailwind.
- [ ] Python dependencies must use major-version-compatible top-level ranges and be resolved to exact versions in `uv.lock`.
- [ ] Frontend dependencies must be resolved from latest stable releases at scaffold time and locked in `pnpm-lock.yaml`.
- [ ] The local dev workflow must provide a single command, preferably `pnpm dev`, that starts all required local services.
- [ ] The default local workflow must use `pnpm` scripts and terminate the complete service process tree on one interrupt.
- [ ] The backend must avoid relying on the system Python version.

Acceptance criteria:

- [ ] `uv run python --version` reports Python 3.12.x.
- [ ] `uv sync` installs the backend reproducibly.
- [ ] `pnpm install` installs the frontend reproducibly.
- [ ] Dependency lock files are committed after initial scaffold.
- [ ] `pnpm dev` starts the frontend and required backend protocol services.
- [ ] A new developer can start the full local app from README instructions.

### FR-2: SAP AI Core Model Integration

- [ ] The backend must create the DeepAgent model as an initialized SAP LangChain-compatible chat model instance, not as a DeepAgents `provider:model` string.
- [ ] The first model initialization path must use `gen_ai_hub.proxy.langchain.init_llm(model_name=...)` with model name loaded from configuration.
- [ ] The SAP SDK must remain responsible for resolving the configured model name to the relevant GenAI Hub provider/deployment.
- [ ] The initialized model must be verified as usable by DeepAgents and LangChain chat flows.
- [ ] The initialized model must support DeepAgent tool calling, including `bind_tools()`.
- [ ] If `init_llm(...)` returns a model that does not satisfy DeepAgent/tool-calling requirements, the implementation may fall back to an explicit SAP SDK wrapper such as `gen_ai_hub.proxy.langchain.ChatOpenAI(proxy_model_name=...)`.
- [ ] The default local model name must be `anthropic--claude-4.6-sonnet`, assuming that name matches the developer's configured SAP GenAI Hub / AI Core model or deployment alias.
- [ ] SAP AI Core authentication should default to the SAP SDK's configured credential discovery, such as local SDK config, environment variables, or `VCAP_SERVICES`.
- [ ] Explicit `AICORE_*` environment variables may be used as local overrides, but are not required when SDK authentication is already configured.
- [ ] SAP AI Core credentials must never be read from frontend code.
- [ ] The backend must fail fast with a clear error if SAP AI Core model initialization or discovery fails.

Reference implementation direction:

```python
from gen_ai_hub.proxy.langchain import init_llm

model = init_llm(
    model_name="<configured-model-name>",
    temperature=0,
)
```

Fallback direction if the primary path cannot satisfy chat/tool-calling requirements:

```python
from gen_ai_hub.proxy import get_proxy_client
from gen_ai_hub.proxy.langchain import ChatOpenAI

proxy_client = get_proxy_client("gen-ai-hub")
model = ChatOpenAI(
    proxy_model_name="<configured-model-name>",
    proxy_client=proxy_client,
    temperature=0,
)
```

Acceptance criteria:

- [ ] Backend can initialize the configured SAP model through `init_llm(...)` or a documented fallback.
- [ ] With local SAP SDK authentication already configured, backend model initialization works without setting `AICORE_*` values in the project `.env`.
- [ ] A direct model invocation smoke test succeeds in the configured environment.
- [ ] A `model.bind_tools([...])` smoke test succeeds before connecting the model to DeepAgents.
- [ ] A DeepAgent tool-call smoke test succeeds with the initialized model.

### FR-3: DeepAgent Construction With Official Defaults, Skills, and No Memory

- [ ] The backend must construct the agent with `create_deep_agent(...)`.
- [ ] The agent must use official DeepAgents defaults unless explicitly required otherwise in this document.
- [ ] The backend must not pass `memory=` and must not seed AGENTS.md memory files.
- [ ] Runtime checkpointer/thread/run state must remain enabled where needed for `/chat` continuity, interrupt/resume, and A2A task mapping.
- [ ] The backend must pass configured `tools=` loaded from MCP and optional local smoke-test tools.
- [ ] The backend must support configurable `system_prompt`, but the default must be empty/unset and current development must use DeepAgents official default prompt behavior.
- [ ] The backend must support `skills` configuration through local filesystem paths.
- [ ] If skills paths are configured, the backend must pass them to `create_deep_agent(skills=[...])`.
- [ ] If skills paths are empty, the backend must omit `skills=` and preserve official default behavior.
- [ ] The first version must use the official default general-purpose subagent behavior and must not require custom `subagents=[...]`.
- [ ] The configuration schema must reserve space for future custom subagents with `name`, `description`, `system_prompt`, `tools`, `skills`, and optional model override.
- [ ] Other optional DeepAgents features such as custom middleware, custom interrupt rules, and custom filesystem/backend must remain unconfigured unless needed to support skills or runtime checkpointing.

Reference implementation direction:

```python
from deepagents import create_deep_agent

kwargs = {
    "model": model,
    "tools": tools,
}

if configured_system_prompt:
    kwargs["system_prompt"] = configured_system_prompt

if configured_skill_paths:
    kwargs["skills"] = configured_skill_paths

agent = create_deep_agent(
    **kwargs,
    # memory intentionally omitted
    # subagents intentionally omitted for first version
)
```

Acceptance criteria:

- [ ] Agent can answer a simple chat prompt.
- [ ] Agent can call at least one configured MCP tool.
- [ ] Agent can load configured local-path skills.
- [ ] Main agent and default general-purpose subagent can access agent-level skills where DeepAgents supports inheritance.
- [ ] No DeepAgents long-term/semantic memory path/files are configured or loaded.
- [ ] Thread continuity works through runtime state even though DeepAgents memory is not configured.

### FR-4: MCP Tool Configuration

- [ ] MCP servers must be deployment-level fixed configuration for the first version.
- [ ] MCP servers must be configured through a backend config file or environment-configured config path.
- [ ] Runtime/user-level MCP configuration must not be implemented in the first version.
- [ ] The MCP configuration must support at least:
  - [ ] local stdio MCP servers with `command` and `args`;
  - [ ] remote HTTP/streamable HTTP MCP servers with `url`;
  - [ ] optional headers for auth/tracing;
  - [ ] `required: true/false` for each configured MCP server.
- [ ] The backend must load MCP tools at startup using `langchain_mcp_adapters.client.MultiServerMCPClient` or equivalent official LangChain MCP adapter.
- [ ] If a required MCP server fails to load, backend startup must fail fast.
- [ ] If an optional MCP server fails to load, backend startup may continue but must log and expose a warning through health/status metadata.
- [ ] The same MCP tools must be available to `/chat` and `/a2a` because both protocols call the same DeepAgent capability surface.
- [ ] The first required MCP server must be `dynatrace-managed`, launched through `npx -y @dynatrace-oss/dynatrace-managed-mcp-server@1.0.0`.
- [ ] MCP server package versions must be pinned in committed example config; upgrades must be explicit version bumps, not silent `@latest` drift.
- [ ] Dynatrace MCP tokens must be supplied through local environment variables or uncommitted local config, never hard-coded in committed files.

Reference implementation direction from LangChain docs:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "math": {
        "transport": "stdio",
        "command": "python",
        "args": ["/path/to/math_server.py"],
    },
    "weather": {
        "transport": "http",
        "url": "http://localhost:8000/mcp",
    },
})
tools = await client.get_tools()
```

Acceptance criteria:

- [ ] `config/mcp.example.json` includes the `dynatrace-managed` MCP server template.
- [ ] At least one stdio MCP server can be configured and its tools appear in the agent tool list.
- [ ] At least one HTTP MCP server can be configured and its tools appear in the agent tool list.
- [ ] A `/chat` prompt can trigger a tool loaded from MCP.
- [ ] An `/a2a` message can trigger the same MCP tool.
- [ ] Required MCP startup failure fails the service.
- [ ] Optional MCP startup failure is visible without failing the service.

Sources: [LangChain MCP](https://docs.langchain.com/oss/python/langchain/mcp), [DeepAgents MCP](https://docs.langchain.com/oss/python/deepagents/mcp), [MCP transports](https://modelcontextprotocol.io/registry/remote-servers)

### FR-5: Langfuse Trace Recording

- [ ] The backend must record LangChain/LangGraph/DeepAgents runs to Langfuse.
- [ ] Langfuse credentials and host must be configured via environment variables when tracing is enabled.
- [ ] If Langfuse keys are missing in local development, the backend must start with tracing disabled, log a clear warning, and expose tracing status in health/status metadata.
- [ ] The backend should attach `langfuse.langchain.CallbackHandler` to the compiled graph or per-run config.
- [ ] Traces must cover both `/chat` and `/a2a` calls.
- [ ] Trace metadata must identify the protocol entrypoint, such as `protocol=chat` or `protocol=a2a`.
- [ ] Trace metadata must include thread id, run id, and A2A task/context id where available.
- [ ] Trace events/spans should include SAP AI Core model calls, MCP tool calls, DeepAgents subagent delegation, todos/progress/state values where available, interrupts/resume, stream/run metadata, and A2A method names.
- [ ] Short-lived scripts/tests must flush Langfuse before exit.

Reference implementation direction from Langfuse docs:

```python
from langfuse.langchain import CallbackHandler

langfuse_handler = CallbackHandler()
agent = agent.with_config({"callbacks": [langfuse_handler]})
```

Required environment variables when tracing is enabled:

- [ ] `LANGFUSE_PUBLIC_KEY`
- [ ] `LANGFUSE_SECRET_KEY`
- [ ] `LANGFUSE_BASE_URL`

Acceptance criteria:

- [ ] A `/chat` run creates a trace in Langfuse.
- [ ] An `/a2a` run creates a trace in Langfuse.
- [ ] With missing Langfuse keys in local development, the app still starts and health/status reports tracing disabled.
- [ ] The trace contains model and MCP tool-call spans/events.
- [ ] Trace metadata includes at least environment, assistant/graph id, protocol, thread id, and A2A task id where applicable.
- [ ] Interrupt/resume or subagent events are visible when the underlying run emits them.

Sources: [Langfuse LangGraph integration](https://github.com/langfuse/langfuse-docs/blob/main/content/guides/cookbook/integration_langgraph.mdx), [Langfuse LangChain integration](https://github.com/langfuse/langfuse-docs/blob/main/content/integrations/frameworks/langchain.mdx)

### FR-6: API Requirements: `/chat/*` and `/a2a/*`

- [ ] `/chat` must be a protocol base path, not a single custom `POST /chat` endpoint.
- [ ] `/chat/*` must be fully compatible with the official `@langchain/react useStream` client without a custom frontend transport.
- [ ] `/chat/*` must expose the DeepAgent through the official DeepAgents/LangGraph-compatible frontend protocol expected by `useStream({ apiUrl, assistantId })`.
- [ ] `/chat/*` must accept message-based state compatible with LangGraph/DeepAgents, with user input carried under the `messages` key.
- [ ] `/chat/*` must support streaming output, thread continuity, and run resume semantics required by the official SDK.
- [ ] The implementation should reuse official LangGraph/DeepAgents server behavior wherever possible instead of hand-rolling protocol details.
- [ ] If direct route mounting into one backend process is not practical, a local gateway, reverse proxy, or Vite dev proxy may route `/chat/*` to an official LangGraph dev/server process.
- [ ] The first implementation should use official `langgraph dev` or the equivalent local LangGraph server for `/chat/*`, exposed under `/chat` through Vite dev proxy or a thin local gateway.
- [ ] Protocol compatibility with official `useStream` takes priority over forcing all local services into one OS process.
- [ ] `/a2a` must be a protocol base path for Google open-source Agent2Agent protocol routes.
- [ ] `/a2a/*` must be implemented with the official A2A Python SDK or official server components where available.
- [ ] `/a2a/*` must call the same DeepAgent capability surface as `/chat/*`.
- [ ] `/a2a/*` must provide agent discovery through an Agent Card, routed under `/a2a` or proxied from the official A2A route shape.
- [ ] The first implementation must expose official A2A JSON-RPC under `/a2a/jsonrpc` and agent-card discovery under `/a2a/.well-known/agent-card.json`.
- [ ] `/a2a/*` should support official send-message, streaming send-message, and task status/result retrieval operations through the official SDK surface.
- [ ] A2A REST routes are not required for the first local baseline if they conflict with the current compatible LangGraph local-server dependency graph; do not advertise unsupported REST interfaces in the Agent Card.
- [ ] A2A task state may use an in-memory task store for the first version and only needs to survive within the current local process lifetime.
- [ ] `/chat` and `/a2a` protocol state must remain layered: `/chat` exposes LangGraph thread/run semantics, while `/a2a` exposes A2A task/context/message semantics.
- [ ] A2A adapter code may create or map to LangGraph threads internally, but must not require `a2a_task_id == langgraph_thread_id`.
- [ ] Both `/chat` and `/a2a` requests must attach Langfuse callbacks and include protocol mapping metadata in traces.
- [ ] The backend must keep SAP AI Core, MCP, Langfuse, and any platform API secrets server-side.

Acceptance criteria:

- [ ] A Vite React frontend can call `useStream({ apiUrl: "<local-base>/chat", assistantId: "agent" })` without a custom transport.
- [ ] A user can send a message through `/chat/*` and receive streamed output.
- [ ] Chat conversation continuity works from a stable LangGraph thread id.
- [ ] Refreshing the page can recover a conversation from thread id/history metadata.
- [ ] An A2A client can discover the agent card through the `/a2a` surface.
- [ ] An A2A JSON-RPC client can send a non-streaming message and receive a complete response.
- [ ] An A2A JSON-RPC client can send a streaming message and receive protocol-compatible stream events.
- [ ] An A2A JSON-RPC client can retrieve task status/result for an active or completed task in the current process lifetime.
- [ ] Chat API and A2A API calls both appear in Langfuse with protocol, thread/task id, and mapping metadata.

Sources: [LangGraph local server API](https://docs.langchain.com/oss/python/langgraph/local-server), [DeepAgents frontend overview](https://docs.langchain.com/oss/python/deepagents/frontend/overview), [A2A protocol definitions](https://a2a-protocol.org/latest/definitions), [A2A agent discovery](https://a2a-protocol.org/latest/topics/agent-discovery)

### FR-7: Frontend Chat Experience

- [ ] The first frontend must be built with Vite, React, Tailwind, `pnpm`, and official `@langchain/react useStream`.
- [ ] The first frontend must prioritize future extension toward an agent-native ops dashboard over fastest possible demo reuse.
- [ ] Agent Chat UI may be used as a reference implementation, but must not be the default fork/configuration path for the first version.
- [ ] The first frontend must provide a core chat panel.
- [ ] The first frontend must provide thread history list/cache.
- [ ] Thread history truth must live in backend/LangGraph thread state; frontend cache must not be the source of truth.
- [ ] Thread titles must be generated from the first user message by trimming whitespace and truncating to a configured length.
- [ ] The first frontend must display streaming output from `useStream`.
- [ ] The first frontend must handle loading, error, and reconnect/retry states at a basic level.
- [ ] The first frontend must be configurable with `/chat` base URL and assistant id.
- [ ] The frontend must not contain SAP AI Core credentials, Langfuse secret keys, MCP auth headers, or other backend secrets.
- [ ] The frontend code structure must reserve extension points for future ops dashboard panels such as subagents, todos/progress, tool calls, interrupts, trace links, and MCP status.

Acceptance criteria:

- [ ] User can open the frontend, send a message, and see streamed agent output.
- [ ] User can create a new thread and switch between cached/retrieved thread history entries.
- [ ] Existing thread can be restored by thread id after refresh.
- [ ] Thread list title is based on the first user message, with fallback `New chat` if no user message exists.
- [ ] Frontend can target local `/chat` through configuration.
- [ ] Frontend does not expose server secrets in browser-visible env vars.

Recommended direction: start with a small official-SDK frontend using `@langchain/react useStream`, while borrowing interaction ideas from Agent Chat UI where useful. [Frontend research](../research/deepagents-chat-frontends.md)

### FR-8: Configuration and Secrets

- [ ] All runtime values must be configurable without code changes.
- [ ] Required configuration groups:
  - [ ] SAP AI Core / Generative AI Hub model name and optional credential overrides;
  - [ ] MCP server list and required/optional flags;
  - [ ] local skills paths;
  - [ ] Langfuse credentials and environment labels;
  - [ ] assistant id and local protocol ports/base URLs;
  - [ ] frontend `/chat` base URL;
  - [ ] A2A base path/port and task store mode.
- [ ] Local development should use `.env` or `.env.example`; real secrets must not be committed.
- [ ] Local development does not require user authentication.
- [ ] Any shared or deployed environment must add SAP authentication, SSO/RBAC, or an approved gateway in front of `/chat` and `/a2a` before use.

Minimum `.env.example` keys:

```bash
# SAP AI Core / Generative AI Hub
# Leave AICORE_* empty if local SAP SDK authentication is already configured.
AICORE_CLIENT_ID=
AICORE_CLIENT_SECRET=
AICORE_AUTH_URL=
AICORE_BASE_URL=
AICORE_RESOURCE_GROUP=
SAP_AI_CORE_MODEL_NAME=anthropic--claude-4.6-sonnet

# Langfuse
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=https://cloud.langfuse.com

# Agent
APP_ENV=local
ASSISTANT_ID=agent
SYSTEM_PROMPT=
SKILLS_PATHS=./skills/examples/
# Leave empty until Dynatrace tokens are configured locally.
# Set to ./config/mcp.example.json to enable the Dynatrace Managed MCP server.
MCP_CONFIG_PATH=
DT_CONFIG_FILE=./config/dt-config.yaml
DT_PROD_TOKEN=
DT_STAGING_TOKEN=

# Local protocol surfaces
CHAT_BASE_PATH=/chat
A2A_BASE_PATH=/a2a
A2A_TASK_STORE=memory

# Frontend
VITE_CHAT_API_URL=/chat
VITE_A2A_API_URL=/a2a
VITE_ASSISTANT_ID=agent
```

## 5. Non-Functional Requirements

### NFR-1: Security

- [ ] SAP AI Core credentials, Langfuse secret key, MCP auth headers, and any platform secrets must remain backend-only.
- [ ] Frontend public variables must contain only non-secret values.
- [ ] Logs must not print credentials or full auth headers.
- [ ] Local development may run without user authentication.
- [ ] Shared or deployed environments must not expose unauthenticated `/chat` or `/a2a` endpoints.

### NFR-2: Observability

- [ ] Each `/chat` run must have a traceable thread/run id.
- [ ] Each `/a2a` run must have a traceable A2A task/context/message id where available.
- [ ] Startup logs must show selected model name/deployment, MCP server names, skills paths, protocol surfaces, and tracing status without exposing secrets.
- [ ] Trace metadata must make it possible to correlate A2A task ids with internal LangGraph thread/run ids when the adapter creates such mappings.

### NFR-3: Reliability

- [ ] Backend startup should validate required configuration.
- [ ] If required MCP servers fail, backend should fail fast.
- [ ] If optional MCP servers fail, backend should continue with warnings.
- [ ] If configured skills paths are missing or invalid, backend should fail fast.
- [ ] SAP model/tool-calling smoke tests should be available as a developer command.
- [ ] A2A in-memory task store limitations must be documented.

### NFR-4: Extensibility

- [ ] Adding MCP servers must not require code changes.
- [ ] Adding local skills paths must not require code changes.
- [ ] Adding future custom subagents should be possible through configuration shape, even if not enabled in the first version.
- [ ] Adding local tools should be isolated in a tools module.
- [ ] Frontend architecture should support later ops dashboard panels without replacing the official `useStream` foundation.

### NFR-5: Local Development Ergonomics

- [ ] `pnpm dev` must be the default full-stack local startup command.
- [ ] The local dev setup may run multiple processes if needed to preserve official protocol compatibility.
- [ ] Documentation must include individual backend/frontend commands for troubleshooting.
- [ ] Port conflicts and expected local URLs must be documented.

## 6. Suggested Milestones

### M1: Project Skeleton and Dev Orchestration

- [ ] Initialize `uv` Python 3.12 backend project.
- [ ] Initialize Vite + React + Tailwind frontend managed by `pnpm`.
- [ ] Add a cross-platform `pnpm dev` process supervisor.
- [ ] Add `.env.example` and config loader.
- [ ] Add health/startup checks.

### M2: SAP Model + DeepAgent

- [ ] Load SAP model via `init_llm(model_name=...)`.
- [ ] Verify chat invocation and `bind_tools()`.
- [ ] Construct `create_deep_agent(model=..., tools=..., skills=...)` with memory omitted.
- [ ] Use official default `system_prompt` and default general-purpose subagent behavior.
- [ ] Run direct CLI/local smoke test.

### M3: MCP and Skills Support

- [ ] Define `config/mcp.example.json` with required/optional MCP server examples.
- [ ] Load stdio/http MCP tools.
- [ ] Add one sample MCP tool/server for local testing.
- [ ] Add local skills path configuration.
- [ ] Verify skills load and are available to the agent.

### M4: `/chat/*` Official Frontend Protocol

- [ ] Expose `/chat` as a base path compatible with `@langchain/react useStream`.
- [ ] Preserve official protocol compatibility even if this requires a local gateway/proxy to a LangGraph dev/server process.
- [ ] Verify streamed response and thread continuity.
- [ ] Verify refresh recovery by thread id.

### M5: `/a2a/*` Google A2A Protocol

- [ ] Integrate official A2A Python SDK or official server components.
- [ ] Expose `/a2a` as the A2A base path.
- [ ] Expose `/a2a/.well-known/agent-card.json` and `/a2a/jsonrpc` in the first local baseline.
- [ ] Implement DeepAgent executor/adapter for A2A requests.
- [ ] Use in-memory A2A task store for local development.
- [ ] Verify agent card discovery.
- [ ] Verify JSON-RPC non-streaming send, streaming send, and task retrieval flows.

### M6: Langfuse Trace

- [ ] Add Langfuse callback handler.
- [ ] Verify traces for `/chat` model/tool/subagent events.
- [ ] Verify traces for `/a2a` message/task flows.
- [ ] Add protocol, thread, run, task, MCP, and skills metadata where available.

### M7: Frontend Core Chat

- [ ] Build Vite React chat panel using `@langchain/react useStream`.
- [ ] Build thread history list/cache backed by backend/LangGraph thread state.
- [ ] Add streaming output rendering.
- [ ] Add loading/error/reconnect states.
- [ ] Reserve layout/code extension points for future ops dashboard panels.

### M8: Hardening and Documentation

- [ ] Add config validation.
- [ ] Add smoke tests.
- [ ] Document local startup and troubleshooting commands.
- [ ] Document local-only auth posture and future SAP auth requirement for shared environments.
- [ ] Document secret handling guidance.

## 7. Open Questions

- [ ] What SAP authentication/SSO/RBAC approach should be used before exposing the app beyond local development? This is not blocking for local-first development.

## 8. Initial Done Definition

The first version is done when:

- [ ] `uv` runs the backend with Python 3.12.
- [ ] `pnpm dev` starts the full local app stack.
- [ ] Backend initializes a SAP AI Core chat model through `init_llm(model_name=...)` or a documented fallback.
- [ ] Python top-level dependency ranges, including `a2a-sdk[http-server]>=1.1.2,<2`, are exact-resolved in `uv.lock`.
- [ ] Frontend dependencies are locked in `pnpm-lock.yaml`.
- [ ] Backend constructs a DeepAgent with memory omitted, official default prompt behavior, default general-purpose subagent behavior, configured MCP tools, and configured local skills.
- [ ] Runtime thread/checkpoint state supports chat continuity even though DeepAgents long-term/semantic memory is not configured.
- [ ] At least one MCP tool is loaded from deployment-level configuration and callable through both `/chat` and `/a2a`.
- [ ] The `dynatrace-managed` MCP server can be configured from `config/mcp.example.json` with real local tokens supplied outside source control.
- [ ] The local skills path `./skills/examples/` can be configured and loaded.
- [ ] A Vite React frontend can chat with the backend through `/chat/*` using official `@langchain/react useStream` without a custom transport.
- [ ] Frontend shows core chat panel, thread history list/cache, and streamed output.
- [ ] A Google A2A JSON-RPC client can discover the agent through `/a2a`, send non-streaming and streaming messages, and retrieve task status/results within the current process lifetime.
- [ ] `/chat` and `/a2a` calls both appear in Langfuse with model/tool trace details and protocol/thread/task metadata.
- [ ] Local startup succeeds without Langfuse keys and reports tracing disabled.
- [ ] Secrets are only configured server-side and are not exposed to the frontend.
