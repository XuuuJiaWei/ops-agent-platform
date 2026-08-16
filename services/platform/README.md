# OpsPilot platform host

This package owns executable composition and lifecycle: configuration loading,
FastAPI, CopilotKit/AG-UI, A2A, health endpoints, Spaces storage, LangGraph
export, and benchmark adapters. It depends on the host-neutral `ops-pilot`
agent harness; the harness never imports this package.
