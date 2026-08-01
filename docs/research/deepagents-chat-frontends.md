# DeepAgents Chat Frontend Options

Date: 2026-07-31

## Core recommendation

Decision update after requirements alignment: for the first implementation, use a small custom Next.js + Tailwind frontend built directly on the official `@langchain/react` `useStream` SDK. Agent Chat UI remains a useful reference implementation, but it is no longer the preferred first-version fork/configuration path because the product needs lowest long-term extension cost for an agent-native ops dashboard.

Earlier evaluation: **LangChain Agent Chat UI** is still the fastest path to a generic chat demo connected to a LangGraph/DeepAgents server. It is a Next.js app for chatting with any LangGraph server that has a `messages` key, can be created with `npx create-agent-chat-app`, and can be preconfigured with `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_ASSISTANT_ID`. Use it as a reference or fallback when speed matters more than long-term dashboard extensibility. [Agent Chat UI README](https://github.com/langchain-ai/agent-chat-ui)

For the product path, build or fork a React frontend around **`@langchain/react` `useStream`**. DeepAgents' official frontend docs say the SDK exposes more than chat messages: `stream.messages`, `stream.subagents`, `stream.values`, tool-call state, and interrupts. That is the interface we need if users should see delegation, task progress, todos, approvals, filesystem/sandbox artifacts, or SAP-specific workflow state. [DeepAgents frontend overview](https://docs.langchain.com/oss/python/deepagents/frontend/overview.md)

Use **assistant-ui** if we want polished chat components and are comfortable wiring a LangGraph runtime/adapter. Use **CopilotKit/AG-UI** if the product should become an agent-native app with frontend tools, shared UI state, generative UI, and human-in-the-loop interactions. Use **Chainlit** only for a fast Python-first demo; it integrates with LangChain/LangGraph, but it does not naturally expose DeepAgents' richer frontend projections. [assistant-ui](https://github.com/assistant-ui/assistant-ui), [CopilotKit](https://github.com/CopilotKit/CopilotKit), [Chainlit LangChain/LangGraph docs](https://docs.chainlit.io/integrations/langchain.md)

## What DeepAgents frontends need

DeepAgents is not just a chatbot runtime. The official frontend docs describe a coordinator-worker architecture where the main agent delegates to subagents, and the frontend should make that delegation visible. The `useStream` handle exposes coordinator messages, live subagent discovery, shared values such as todos/plans/custom state, tool-call state, and interrupts. [DeepAgents frontend overview](https://docs.langchain.com/oss/python/deepagents/frontend/overview.md)

This matters for our SAP AI SDK path because SAP credentials and model calls stay server-side; the frontend talks to a LangGraph/DeepAgents server. So frontend selection should optimize for LangGraph streaming, thread state, tool-call rendering, approval flows, and custom panels, not for model-provider support.

## Shortlist

| Option | Direct DeepAgents/LangGraph fit | What it gives us | Gaps / cost | License / maturity signal |
| --- | --- | --- | --- | --- |
| LangChain Agent Chat UI | Very high for generic chat with a LangGraph server | Ready Next.js app, setup form/env vars, local/prod LangGraph connection, artifact side panel, message hiding conventions | Generic `messages` UI; DeepAgents subagents/todos/interrupts need customization | MIT; GitHub API showed ~3k stars; official LangChain repo |
| Custom React with `@langchain/react` `useStream` | Highest for DeepAgents-specific UX | Native access to `stream.messages`, `stream.subagents`, `stream.values`, tool-call state, interrupts | We build the UI shell ourselves or fork Agent Chat UI | `@langchain/react` is MIT on npm; official runtime path |
| assistant-ui + LangGraph starter | High with adapter | Polished React chat primitives, starter repo for LangGraph, strong component base | Need to map LangGraph/DeepAgents events into assistant-ui runtime; DeepAgents projections are not automatic | MIT; GitHub API showed ~11k stars for assistant-ui |
| CopilotKit / AG-UI | High for rich agent-native apps | Chat UI, tool-call UI, shared state, frontend tools, human-in-the-loop, generative UI, AG-UI protocol | More opinionated; likely more integration work if we already serve standard LangGraph API | MIT; GitHub API showed ~36k stars |
| Chainlit | Medium | Python-first app, LangChain/LangGraph examples, streaming via callback handler | Less suitable for subagent/todo/artifact panels and custom product UX | Apache-2.0; GitHub API showed ~12k stars |
| Streamlit / Gradio | Low-medium | Fast demos | Mostly custom plumbing for threads, tool calls, interrupts, subagents | Apache-2.0; large ecosystems |
| Open WebUI / LibreChat | Low for DeepAgents | Mature general chat shells | LLM/OpenAI-API centric; LangGraph/DeepAgents adapter would be substantial | Open WebUI and LibreChat are mature, but not the shortest path here |

## Option notes

### 1. LangChain Agent Chat UI

Best first experiment. The README says Agent Chat UI is a Next.js app for interacting with any LangGraph server with a `messages` key. It can be created with `npx create-agent-chat-app`, asks for Deployment URL, Assistant/Graph ID, and optional LangSmith API key, and can skip the setup screen with `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_ASSISTANT_ID`, and `NEXT_PUBLIC_AUTH_SCHEME`. [Agent Chat UI README](https://github.com/langchain-ai/agent-chat-ui)

It also documents production API passthrough so the browser does not need each user's LangSmith API key. That is important if we deploy a SAP-backed DeepAgent where SAP/LangSmith secrets must stay server-side. [Agent Chat UI README](https://github.com/langchain-ai/agent-chat-ui)

Recommended use: fork it, connect to `langgraph dev` or the deployed DeepAgents graph, then add DeepAgents-specific panels from `@langchain/react` patterns.

### 2. Custom DeepAgents frontend with `@langchain/react`

Best long-term route. The DeepAgents docs show `useStream<typeof agent>({ apiUrl, assistantId })`, then reading `stream.values?.todos` and `stream.subagents`. The same page explicitly lists tool-call state and interrupts as frontend projections. [DeepAgents frontend overview](https://docs.langchain.com/oss/python/deepagents/frontend/overview.md)

This is the only route that cleanly supports a UI shaped like an operations console: left chat, center progress/todos, right tool/artifact pane, approvals inline, and subagent cards. It is also less likely to fight the underlying DeepAgents model as the LangGraph runtime evolves.

### 3. assistant-ui

assistant-ui is a React/TypeScript library for production-grade AI chat experiences; npm reports `@assistant-ui/react` as MIT, and the official LangGraph starter expects `LANGGRAPH_API_URL`, `LANGCHAIN_API_KEY`, and `NEXT_PUBLIC_LANGGRAPH_ASSISTANT_ID`. [assistant-ui npm metadata](https://www.npmjs.com/package/@assistant-ui/react), [assistant-ui LangGraph starter](https://github.com/assistant-ui/assistant-ui-starter-langgraph)

This is attractive if we want a polished chat shell and are willing to write a runtime bridge. It is less direct than Agent Chat UI for a plain LangGraph server, but likely better if we care about reusable components and design polish.

### 4. CopilotKit / AG-UI

CopilotKit's README positions it as a frontend stack for agentic applications with chat UI, tool calls, shared state, human-in-the-loop, backend tool rendering, and generative UI. It also says CopilotKit is behind AG-UI, an agent-user interaction protocol. [CopilotKit README](https://github.com/CopilotKit/CopilotKit)

Context7 found CopilotKit docs for LangGraph integration that wire CopilotKit state/actions into LangGraph using `CopilotKitStateAnnotation` and convert frontend actions into LangChain tools with `convertActionsToDynamicStructuredTools`. It also found a Deep Agents quickstart note saying AG-UI is a frontend-agent protocol that Deep Agents use to stream state and tool calls in real time. [CopilotKit LangGraph reference](https://github.com/copilotkit/copilotkit/blob/main/skills/copilotkit-integrations/references/integrations/langgraph.md), [CopilotKit Deep Agents quickstart](https://github.com/copilotkit/copilotkit/blob/main/showcase/shell-docs/src/content/docs/integrations/deepagents/quickstart.mdx)

This is the most ambitious option: good for an app where the agent manipulates the UI, asks for approvals, and calls frontend tools. It is more architecture than we need for a basic chat frontend.

### 5. Chainlit

Chainlit's docs include both LangChain and LangGraph examples. The LangGraph example streams graph messages and uses `cl.LangchainCallbackHandler()` plus a `thread_id` based on the Chainlit session. [Chainlit LangChain/LangGraph docs](https://docs.chainlit.io/integrations/langchain.md)

This is useful for quickly proving the backend works with a UI, especially because it is Python-first. The cost is that DeepAgents-specific subagent streams, todo state, interrupts, and artifact panels would be custom Chainlit work rather than native `useStream` projections.

## Recommended architecture

1. Serve our SAP-backed DeepAgent as a LangGraph server. The frontend should never receive SAP AI Core credentials.
2. Prototype with Agent Chat UI using `NEXT_PUBLIC_API_URL=http://localhost:2024` and `NEXT_PUBLIC_ASSISTANT_ID=<graph-id>`.
3. In parallel, start a custom React shell based on `@langchain/react` `useStream`, borrowing layout/components from Agent Chat UI or assistant-ui.
4. Add panels in this order: message stream, tool-call cards, todos/progress from `stream.values`, subagent cards from `stream.subagents`, then interrupt approval UI.
5. Consider CopilotKit only if we need frontend tools/generative UI as a first-class product requirement.

## Bottom line

For this project, I would not start from Open WebUI/LibreChat-style general chat products. They are mature chat applications, but the adaptation layer to DeepAgents' streaming state is the hard part. Start with **Agent Chat UI for speed**, then graduate to a **`useStream` custom frontend** for the real DeepAgents experience.
