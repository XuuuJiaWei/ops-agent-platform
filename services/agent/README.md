# OpsPilot agent harness

This package is host-neutral. It owns DeepAgents construction, models, MCP,
sandbox, skills, persistence, reliability, and tracing. It does not load YAML,
start a server, expose a protocol, or import a product domain.

Executable composition lives in the sibling `services/platform` package.
Consumers inject domain tools and LangChain middleware through `RuntimeSpec`.
