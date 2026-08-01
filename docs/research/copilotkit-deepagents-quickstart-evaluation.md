# CopilotKit Deep Agents Quickstart Evaluation

Date: 2026-08-01

## Question

Evaluate the CopilotKit Deep Agents quickstart for this repository: whether it requires uploading company data to CopilotKit, whether it can connect to the existing DeepAgents/LangGraph backend, and whether it is a good route toward a future frontend ops dashboard with panels for subagents, todos, tool calls, interrupts, traces, and MCP status.

## Short Answer

CopilotKit does **not** inherently require company data to be uploaded to CopilotKit for the basic Deep Agents quickstart if the app points `<CopilotKit runtimeUrl="/api/copilotkit">` at a runtime that we host, because the quickstart wires the frontend to a local `/api/copilotkit` route and that route forwards to a LangGraph deployment URL and graph id we control. [CopilotKit quickstart runtime route](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L258-L302), [CopilotKit quickstart provider](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L338-L359)

CopilotKit **does** involve CopilotKit-hosted services when using Cloud-Hosted Enterprise Intelligence or the provider's cloud fallback, and those hosted features store or process thread/event data. CopilotKit's cloud docs say the hosted service stores project-scoped platform data including threads, events, runtime connection metadata, and API keys; its thread inspection page exposes recorded event timelines and raw event payloads for debugging. [Cloud-hosted Enterprise Intelligence data scope](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/premium/managed-intelligence-platform.mdx#L21-L27), [cloud thread inspection and raw event payloads](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/premium/managed-intelligence-platform.mdx#L56-L69)

It can connect to an existing LangGraph/DeepAgents backend, but not by pointing CopilotKit React directly at this repo's raw `/chat` LangGraph endpoint. The documented shape is an adapter layer: either a Node/Next Copilot Runtime with `LangGraphAgent({ deploymentUrl, graphId })`, or a Python FastAPI AG-UI endpoint mounted alongside the LangGraph deployment. [CopilotKit quickstart `LangGraphAgent`](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L272-L302), [LangChain CopilotKit integration architecture](https://docs.langchain.com/oss/python/langchain/frontend/integrations/copilotkit.md), [LangChain FastAPI AG-UI endpoint pattern](https://docs.langchain.com/oss/python/langchain/frontend/integrations/copilotkit.md)

For this repo, CopilotKit is a promising **secondary experiment** for richer tool rendering, frontend tools, HITL, and generative UI, but it is not the best primary path for the ops dashboard right now. The repo already uses the LangGraph frontend stream directly, and the official LangGraph frontend docs say `useStream` exposes graph-native concepts such as nodes, state keys, checkpoints, interrupts, subgraphs, and streamed messages, which maps more directly to the desired subagent/todo/tool/interrupt/status dashboard. [Repo `useStream` hook](../../apps/web/src/features/chat/hooks/use-deepagent-chat.ts#L30-L66), [repo dashboard consumes `subagents` and `values`](../../apps/web/src/features/ops-dashboard/components/dashboard-shell.tsx#L4-L20), [LangGraph frontend overview](https://docs.langchain.com/oss/python/langgraph/frontend/overview.md)

## Repository Grounding

This repository is explicitly local-first and exposes `/chat/*` for the official LangGraph frontend stream protocol plus `/a2a/*` for Google A2A. [README](../../README.md#L3-L7)

The local dev stack starts a Vite frontend, a LangGraph dev server at `127.0.0.1:2024`, and an A2A server at `127.0.0.1:41241`; the Vite server proxies `/chat` to the LangGraph dev server. [README local stack](../../README.md#L26-L43), [Vite proxy config](../../apps/web/vite.config.ts#L12-L40)

The current frontend already wraps `@langchain/langgraph-sdk/react` `useStream`, submits `messages`, and projects `stream.subagents ?? stream.subgraphs` and `stream.values` into app state. [use-deepagent-chat](../../apps/web/src/features/chat/hooks/use-deepagent-chat.ts#L3-L66)

The existing dashboard shell already receives `subagents` and `values`, and its placeholder panel reads `values?.todos`. [dashboard shell](../../apps/web/src/features/ops-dashboard/components/dashboard-shell.tsx#L4-L20)

The backend graph id is currently `agent` in `services/agent/langgraph.json`, and `graph.py` exports the shared runtime graph object. [langgraph.json](../../services/agent/langgraph.json#L1-L7), [graph export](../../services/agent/src/ops_pilot/agent/graph.py#L1-L14)

The repo's requirements expect Langfuse traces for `/chat` and `/a2a`, including model calls, MCP tool calls, subagent delegation, todos/progress/state values, interrupts/resume, and protocol metadata. [Langfuse requirements](../requirements/deepagent-sap-aicore-requirements.md#L232-L268)

The backend already has an MCP status shape with per-server `ok`, `required`, `transport`, `tool_count`, and `error` fields, and the runtime status endpoint includes that MCP status plus tracing status. [MCP status shape](../../services/agent/src/ops_pilot/mcp/status.py#L9-L59), [runtime status composition](../../services/agent/src/ops_pilot/health/status.py#L12-L30)

## What The CopilotKit Quickstart Actually Wires

The quickstart asks users to create a free Enterprise Intelligence account for a license key, saying that the key will later enable persistent threads and the inspector. [Quickstart account step](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L27-L30)

The agent examples add CopilotKit middleware to a Deep Agent in Python or TypeScript, and the Python FastAPI tab exposes the graph as an AG-UI endpoint with `add_langgraph_fastapi_endpoint` and `LangGraphAGUIAgent`. [Python middleware example](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L82-L96), [FastAPI AG-UI example](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L165-L223)

The Next.js route example creates a Copilot Runtime endpoint and registers `sample_agent` as a `LangGraphAgent` pointing at `LANGGRAPH_DEPLOYMENT_URL` or `http://localhost:8123` with `graphId: "sample_agent"`. [Next route `LangGraphAgent`](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L272-L302)

The provider example wraps the app with `<CopilotKit runtimeUrl="/api/copilotkit" agent="sample_agent">`, so the frontend talks to the app-hosted Copilot Runtime endpoint rather than directly to CopilotKit Cloud. [Provider example](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L338-L359)

CopilotKit's provider source defines the cloud chat endpoint as `https://api.cloud.copilotkit.ai/copilotkit/v1`, but it chooses `runtimeUrl` first and only falls back to that cloud URL when a public key is supplied without a runtime URL. [Provider cloud constant](https://github.com/CopilotKit/CopilotKit/blob/main/packages/react-core/src/v2/providers/CopilotKitProvider.tsx#L81-L84), [provider endpoint selection](https://github.com/CopilotKit/CopilotKit/blob/main/packages/react-core/src/v2/providers/CopilotKitProvider.tsx#L472-L484)

The runtime source shows Copilot Runtime is designed to receive a map or factory of `AbstractAgent` instances, and it can apply middleware such as A2UI, MCP Apps, and Open Generative UI at runtime. [runtime agent config](https://github.com/CopilotKit/CopilotKit/blob/main/packages/runtime/src/v2/runtime/core/runtime.ts#L131-L148), [runtime middleware options](https://github.com/CopilotKit/CopilotKit/blob/main/packages/runtime/src/v2/runtime/core/runtime.ts#L64-L82)

## Data Handling Assessment

Basic local/self-hosted CopilotKit runtime mode does not require uploading company data to CopilotKit, because the quickstart route can run in our application and forward to our LangGraph deployment, and the provider can be configured with `runtimeUrl` instead of a CopilotKit Cloud URL. [Quickstart route](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L258-L302), [provider endpoint selection](https://github.com/CopilotKit/CopilotKit/blob/main/packages/react-core/src/v2/providers/CopilotKitProvider.tsx#L472-L484)

Using Cloud-Hosted Enterprise Intelligence is a different data posture: CopilotKit says the cloud-hosted service runs the Enterprise Intelligence Platform for you and stores project-scoped platform data such as threads, events, runtime connection metadata, and API keys. [Cloud-hosted data storage](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/premium/managed-intelligence-platform.mdx#L21-L27)

Enterprise Intelligence is also the platform layer for durable threads, realtime sync, project-scoped history, hosted web app surfaces, and operational visibility. [Enterprise Intelligence roles](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/premium/intelligence-platform.mdx#L21-L29), [inspection and operational history](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/premium/intelligence-platform.mdx#L55-L59)

If persistent threads are enabled through Enterprise Intelligence, CopilotKit's docs say threads are durable platform records and the platform stores event history so conversations can replay after reloads and resume across devices. [thread records and event history](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/premium/intelligence-platform.mdx#L41-L47)

CopilotKit documents a self-hosted Enterprise Intelligence option for cases where the platform must run inside the organization's own Kubernetes cluster, VPC, or data boundary. [cloud vs self-hosted choice](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/premium/managed-intelligence-platform.mdx#L79-L90), [shared hosting model](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/premium/intelligence-platform.mdx#L61-L70)

Recommendation on data: do not use CopilotKit Cloud or Cloud-Hosted Enterprise Intelligence for Dynatrace/SAP/company data until the team explicitly approves that data boundary; if CopilotKit is evaluated, start with local/self-hosted runtime mode and no cloud fallback. This follows the repo's local-first data-safety posture and disabled-by-default external tracing. [repo data-safety note](../../README.md#L40-L43), [provider cloud fallback](https://github.com/CopilotKit/CopilotKit/blob/main/packages/react-core/src/v2/providers/CopilotKitProvider.tsx#L472-L484)

## Fit With This Repo's Backend

A CopilotKit Node/Next adapter can connect to the current LangGraph backend by setting `deploymentUrl` to this repo's LangGraph server, for example `http://localhost:2024`, and `graphId` to `agent`, because the quickstart's `LangGraphAgent` constructor takes those exact fields. [quickstart `deploymentUrl` and `graphId`](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L283-L289), [repo graph id](../../services/agent/langgraph.json#L1-L7)

The main mismatch is frontend/server shape: this repo is currently a Vite SPA with a proxy to LangGraph, while the CopilotKit quickstart uses a Next.js API route as the Copilot Runtime. [Vite app dependency and proxy shape](../../apps/web/vite.config.ts#L12-L40), [quickstart Next route](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L258-L302)

The Python-native alternative is to add a custom HTTP app to `langgraph.json` and expose the graph through FastAPI with `ag_ui_langgraph.add_langgraph_fastapi_endpoint` and `LangGraphAGUIAgent`; LangChain's official CopilotKit integration docs say this mounts a CopilotKit-aware runtime without replacing the underlying LangGraph deployment. [LangChain custom endpoint pattern](https://docs.langchain.com/oss/python/langchain/frontend/integrations/copilotkit.md), [quickstart FastAPI AG-UI example](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L165-L223)

Adding `CopilotKitMiddleware` to the DeepAgent would be required for frontend tools and CopilotKit state/context, according to both the CopilotKit quickstart and LangChain's CopilotKit integration docs. [quickstart middleware note](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L90-L95), [LangChain middleware explanation](https://docs.langchain.com/oss/python/langchain/frontend/integrations/copilotkit.md)

## Dashboard Path Assessment

CopilotKit gives a solid path for chat UI, tool-call rendering, frontend tools, shared state, and HITL. Its quickstart registers a default tool renderer that receives tool name, status, parameters, and result, and CopilotKit docs describe frontend tools as browser-side functions the agent can call to update React state or read browser context. [quickstart tool renderer](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L361-L393), [frontend tools docs](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/frontend-tools.mdx#L10-L42)

CopilotKit has a documented HITL path for both LLM-chosen pauses and graph-enforced LangGraph `interrupt()` checkpoints. [HITL overview](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/human-in-the-loop/index.mdx#L37-L58), [useInterrupt LangGraph contract](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/human-in-the-loop/useInterrupt.mdx#L20-L30)

CopilotKit MCP Apps are useful for interactive UI resources served by MCP servers, but that is not the same as this repo's existing deployment-level MCP tool loading and health/status panel needs. CopilotKit MCP Apps auto-render MCP UI resources in chat; this repo already exposes MCP load status as backend health data that would need a custom panel or state projection. [MCP Apps docs](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/generative-ui/mcp-apps.mdx#L10-L35), [repo MCP status](../../services/agent/src/ops_pilot/mcp/status.py#L9-L59)

For subagents and todos, the direct LangGraph frontend SDK path is currently stronger because official LangGraph docs say the stream handle exposes `stream.subgraphs` and `stream.values`, and this repo already forwards `stream.subagents ?? stream.subgraphs` plus `stream.values` into the dashboard shell. [LangGraph stream projections](https://docs.langchain.com/oss/python/langgraph/frontend/overview.md), [repo stream projections](../../apps/web/src/features/chat/hooks/use-deepagent-chat.ts#L57-L66), [repo dashboard projections](../../apps/web/src/features/ops-dashboard/components/dashboard-shell.tsx#L4-L20)

For traces, CopilotKit Enterprise Intelligence provides project history, thread detail pages, event timelines, and operational visibility, but this repo's required tracing backend is Langfuse with model/MCP/subagent/todo/interrupt spans and protocol metadata. [CopilotKit operational history](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/premium/intelligence-platform.mdx#L55-L59), [repo Langfuse requirements](../requirements/deepagent-sap-aicore-requirements.md#L232-L268)

The CopilotKit Inspector is relevant for debugging CopilotKit actions, readables, agent status, messages, and context, but its docs say the threads tab needs Intelligence for conversation history. [Inspector docs](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/inspector.mdx#L1-L18)

## Recommendation

Keep the current `@langchain/langgraph-sdk` / `@langchain/react` stream-based frontend as the primary path for the ops dashboard. It directly exposes the graph-native concepts this dashboard needs, and the repo has already shaped the UI around `subagents`, `values`, and `todos`. [LangGraph frontend overview](https://docs.langchain.com/oss/python/langgraph/frontend/overview.md), [repo `useDeepAgentChat`](../../apps/web/src/features/chat/hooks/use-deepagent-chat.ts#L30-L66), [repo dashboard shell](../../apps/web/src/features/ops-dashboard/components/dashboard-shell.tsx#L4-L20)

Evaluate CopilotKit as a separate proof of concept only if the product direction needs CopilotKit-specific strengths: rich inline tool cards, frontend tools, graph interrupts rendered as custom UI, A2UI/generative UI, or a CopilotKit-native chat shell. [tool rendering](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx#L361-L393), [frontend tools](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/frontend-tools.mdx#L10-L42), [HITL interrupts](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/human-in-the-loop/useInterrupt.mdx#L20-L30)

If a proof of concept is approved, prefer the Python/FastAPI AG-UI route over migrating the app to Next.js just to host `/api/copilotkit`, because the repo already runs a Python LangGraph service and LangChain documents mounting a CopilotKit route next to the graph API. [LangChain FastAPI AG-UI pattern](https://docs.langchain.com/oss/python/langchain/frontend/integrations/copilotkit.md), [repo LangGraph service export](../../services/agent/src/ops_pilot/agent/graph.py#L1-L14)

Do not enable Cloud-Hosted Enterprise Intelligence for company data until the team intentionally accepts CopilotKit-hosted storage of threads/events/history or chooses the self-hosted Enterprise Intelligence option. [cloud data storage](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/premium/managed-intelligence-platform.mdx#L21-L27), [self-hosting option](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/premium/intelligence-platform.mdx#L61-L70)

