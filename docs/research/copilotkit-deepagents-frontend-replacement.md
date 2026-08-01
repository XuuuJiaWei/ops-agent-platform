# CopilotKit DeepAgents Frontend Replacement Research

Date: 2026-08-01

## Question

Can CopilotKit be used without uploading company data, connect to the current ops_pilot DeepAgents backend, and replace the current handwritten frontend while preserving a path toward a richer ops dashboard?

## Short Answer

Yes, CopilotKit is a serious candidate for replacing the current handwritten chat frontend, especially the message streaming, chat shell, tool-call rendering, and agent-state plumbing. The best next step is a small replacement spike, not a full migration in one jump.

CopilotKit does **not inherently require uploading company data**. The official Deep Agents quickstart supports a local/self-hosted path where the browser calls a Copilot Runtime endpoint, and that runtime connects to a local LangGraph or AG-UI backend. Copilot's Enterprise Intelligence Platform account/license is described in the quickstart as enabling persistent threads and the inspector, not as a requirement for a local basic integration. [CopilotKit Deep Agents quickstart](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx)

It is not zero-change for this repo. Our backend already exports a compiled DeepAgents/LangGraph graph, but it does not currently attach `CopilotKitMiddleware`, and it does not expose a Python AG-UI endpoint. CopilotKit's documented paths require either `LangGraphAgent` against a LangGraph server/deployment, or `LangGraphHttpAgent` against a self-hosted FastAPI AG-UI endpoint. [runtime.py](../../services/agent/src/ops_pilot/agent/runtime.py), [CopilotKit LangGraph wiring](https://github.com/CopilotKit/CopilotKit/blob/main/skills/runtime/references/wiring-langgraph.md), [CopilotKit LangGraph integration](https://github.com/CopilotKit/CopilotKit/blob/main/skills/copilotkit-integrations/references/integrations/langgraph.md)

## What CopilotKit Gives Us

CopilotKit v2 has a prebuilt `CopilotChat` component that wires an agent into a chat view, manages messages, running state, suggestions, input clearing, labels, and slot overrides. This directly replaces a lot of the current `useStream` + message-list + composer glue. [CopilotChat reference](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/reference/components/CopilotChat.mdx)

CopilotKit's `useAgent` hook exposes an AG-UI agent object with `messages`, `state`, `isRunning`, `threadId`, `runAgent`, `setState`, `abortRun`, and subscription hooks for message/state/run changes. That is a better primitive for an ops dashboard than hand-reading every LangGraph stream shape in React. [useAgent reference](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/reference/hooks/useAgent.mdx)

CopilotKit has a wildcard `useDefaultRenderTool` hook that gives a built-in expandable card for any unhandled tool call, or lets us register one catch-all renderer. This is likely the largest immediate win over the current handmade message rendering path. [useDefaultRenderTool reference](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/reference/hooks/useDefaultRenderTool.mdx)

The Deep Agents quickstart explicitly says AG-UI is the frontend-agent protocol used to stream state and tool calls to the frontend in real time, and shows DeepAgents with `CopilotKitMiddleware`. [CopilotKit Deep Agents quickstart](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx)

## Data Upload / Privacy Read

For a local deployment, company prompts, tool args, model outputs, and state do not need to be sent to Copilot Cloud. The local architecture is:

```text
Browser
  -> local /api/copilotkit runtime
  -> local LangGraph or AG-UI backend
  -> our SAP AI Core / MCP / Langfuse integrations
```

The quickstart does ask the user to create a free Enterprise Intelligence Platform account for a license key, but says that key is used later to enable persistent threads and the inspector. Basic local runtime examples use `runtimeUrl="/api/copilotkit"` and a local `CopilotRuntime`. [CopilotKit Deep Agents quickstart](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx), [CopilotKit provider reference](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/reference/components/CopilotKit.mdx)

CopilotKit Cloud-only features are a separate risk category. The provider docs mark features such as hosted guardrails/auth and richer error handling as requiring a public API key / Enterprise Intelligence Platform. If we enable those, runtime metadata, errors, traces, thread data, or chat content may enter CopilotKit-hosted systems depending on feature behavior and terms. We should treat Copilot Cloud features as disabled until security review. [CopilotKit provider reference](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/reference/components/CopilotKit.mdx)

## Fit With Current Backend

The current backend already builds a shared DeepAgent graph with SAP model creation, MCP tools, local skills, optional checkpointer, and Langfuse callbacks. The graph is created by `create_deep_agent(**kwargs)` and exported for LangGraph server imports. [runtime.py](../../services/agent/src/ops_pilot/agent/runtime.py), [graph.py](../../services/agent/src/ops_pilot/agent/graph.py)

Current frontend code talks directly to the LangGraph protocol through `useStream`, using `apiUrl`, `assistantId`, `threadId`, and custom TypeScript projections for `messages`, `values`, and `subagents`. [use-deepagent-chat.ts](../../apps/web/src/features/chat/hooks/use-deepagent-chat.ts)

Current ops dashboard planning already assumes future panels consume official stream projections such as subagents, values, todos, tool calls, artifacts, and interrupts. [ops-dashboard README](../../apps/web/src/features/ops-dashboard/README.md)

CopilotKit can connect in two credible ways:

1. `LangGraphAgent`: use Copilot Runtime to connect to the existing LangGraph server surface with `deploymentUrl` and `graphId`. This is closest to the repo's current `/chat` LangGraph-server direction. It still wants `CopilotKitMiddleware` on the DeepAgent if we want frontend tools/context and richer CopilotKit state. [CopilotKit Deep Agents quickstart](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx), [CopilotKit runtime LangGraph wiring](https://github.com/CopilotKit/CopilotKit/blob/main/skills/runtime/references/wiring-langgraph.md)

2. `LangGraphHttpAgent`: expose the graph as an AG-UI FastAPI endpoint with `ag-ui-langgraph.add_langgraph_fastapi_endpoint` and `copilotkit.LangGraphAGUIAgent`. This is the clean self-hosted CopilotKit pattern but adds a new protocol surface beside `/chat` and `/a2a`. [Migrate to AG-UI](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/langgraph/troubleshooting/migrate-to-agui.mdx), [LangGraphAGUIAgent source](https://github.com/CopilotKit/CopilotKit/blob/main/sdk-python/copilotkit/langgraph_agui_agent.py)

For this repo, option 1 is the lower-disruption spike because we already run `langgraph dev`. Option 2 may be better if CopilotKit's AG-UI rendering behaves more predictably for DeepAgents tool/state events.

## Frontend Replacement Feasibility

CopilotKit can replace most of the handwritten chat layer:

- `CopilotKit` provider replaces our runtime URL context and agent binding.
- `CopilotChat` or `CopilotSidebar` replaces the handwritten chat panel, message list, composer, running state, and basic input behavior.
- `useDefaultRenderTool` gives immediate generic tool-call UI.
- Named `useRenderTool` renderers can replace custom per-tool cards as needed.
- `useAgent` gives the dashboard direct access to messages, state, running status, and thread id.

The current app is Vite, not Next.js. CopilotKit examples commonly put `CopilotRuntime` in a Next.js API route, but CopilotKit also has a generic Node runtime path using `createCopilotRuntimeHandler` and `createCopilotNodeHandler`. We can keep Vite and add a small Node service on another port, then proxy `/api/copilotkit` from Vite/local gateway. [Node runtime example](https://github.com/CopilotKit/CopilotKit/blob/main/examples/v2/runtime/node/src/index.ts), [Node endpoint source](https://github.com/CopilotKit/CopilotKit/blob/main/packages/runtime/src/v2/runtime/endpoints/node.ts)

The replacement is not a free dashboard. CopilotKit's own Deep Agents showcase still keeps local React state for research todos/files/sources and updates it from tool renderers, specifically noting it uses local state plus tool rendering rather than `useCoAgent` because of Python FilesystemMiddleware type mismatch. That suggests CopilotKit removes protocol glue, but business dashboard state still needs explicit mapping. [Deep Agents showcase README](https://github.com/CopilotKit/CopilotKit/blob/main/examples/showcases/deep-agents/README.md), [Deep Agents showcase page](https://github.com/CopilotKit/CopilotKit/blob/main/examples/showcases/deep-agents/src/app/page.tsx), [Deep Agents showcase types](https://github.com/CopilotKit/CopilotKit/blob/main/examples/showcases/deep-agents/src/types/research.ts)

## Backend Changes Needed For A Spike

Minimum backend changes:

- Add Python dependency `copilotkit` to `services/agent/pyproject.toml`.
- Pass `middleware=[CopilotKitMiddleware()]` into `create_deep_agent(...)` when CopilotKit mode is enabled.
- Keep SAP credentials, MCP tokens, Langfuse secrets, and model execution server-side.
- Start with `LangGraphAgent` through the existing LangGraph server to minimize new backend surface area.

If the `LangGraphAgent` route does not expose DeepAgents tool/state events as cleanly as expected, add the AG-UI FastAPI endpoint:

- Add `ag-ui-langgraph`.
- Wrap the compiled graph in `LangGraphAGUIAgent`.
- Mount `add_langgraph_fastapi_endpoint(...)` under a path such as `/agui/agent`.
- Point Copilot Runtime `LangGraphHttpAgent({ url })` at that endpoint.

## Frontend Changes Needed For A Spike

Minimum frontend changes while staying on Vite:

- Add `@copilotkit/react-core`, `@copilotkit/react-ui` if needed, and `@copilotkit/runtime` to the web workspace or a new runtime workspace.
- Add a tiny Node runtime service under `apps/copilot-runtime` or similar.
- Proxy `/api/copilotkit` to that service.
- Wrap the app in `<CopilotKit runtimeUrl="/api/copilotkit" agent="agent">`.
- Replace the current central chat panel with `<CopilotChat agentId="agent" />`.
- Add `useDefaultRenderTool()` first, then named tool renderers for MCP/DeepAgents built-ins.
- Build one dashboard panel from `useAgent({ agentId: "agent" })` state/events to verify extensibility.

## Risks And Unknowns

The main risk is protocol fit: our current frontend uses LangGraph `useStream` projections such as `subagents`, `values`, and interrupts. CopilotKit's AG-UI abstraction exposes messages, state, tool calls, and custom events, but we need a spike to confirm whether all DeepAgents-specific projections we care about survive with enough fidelity. [useAgent reference](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/reference/hooks/useAgent.mdx), [LangGraphAgent source](https://github.com/CopilotKit/CopilotKit/blob/main/packages/runtime/src/lib/runtime/agent-integrations/langgraph/agent.ts)

Another risk is dependency and runtime shape. Staying on Vite means introducing a Node Copilot Runtime service or a gateway; switching to Next.js makes CopilotKit setup simpler but creates broader frontend churn.

Thread persistence needs care. CopilotKit can pass `threadId` through the provider/chat, but persistent threads and inspector are positioned as Enterprise Intelligence Platform capabilities in the quickstart. We should keep local/backend thread state as the source of truth unless and until hosted persistence is approved. [CopilotKit Deep Agents quickstart](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx), [CopilotKit provider reference](https://github.com/CopilotKit/CopilotKit/blob/main/showcase/shell-docs/src/content/reference/components/CopilotKit.mdx)

The CopilotKit middleware can expose app context and optionally state to the model. That is powerful but also a data-leak control point. Default `expose_state` is off in the Python middleware, and any app context or headers forwarded into model calls should be explicitly reviewed. [CopilotKitMiddleware source](https://github.com/CopilotKit/CopilotKit/blob/main/sdk-python/copilotkit/copilotkit_lg_middleware.py)

## Recommendation

Run a 1-2 day replacement spike.

Success criteria:

- Browser chat works through CopilotKit against the existing SAP-backed DeepAgent.
- No Copilot Cloud public API key is required for local chat.
- SAP, MCP, and Langfuse secrets remain server-side.
- A backend tool call appears through default CopilotKit tool rendering without custom message parsing.
- At least one DeepAgents built-in tool event, such as `write_todos`, can populate an ops-dashboard panel.
- Thread id can be controlled or recovered enough to preserve current thread UX direction.

Decision after spike:

- If CopilotKit preserves DeepAgents tool/state events well, replace the handwritten chat shell and keep only product-specific ops panels.
- If CopilotKit hides or normalizes away DeepAgents projections we need, keep the current `@langchain/react`/`useStream` foundation and borrow only selected CopilotKit ideas.

My current bias: try CopilotKit. It looks like the right layer for reducing frontend glue, but the ops dashboard should remain our product surface rather than betting everything on the prebuilt chat component.
