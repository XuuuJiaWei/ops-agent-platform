"""CLI entry point for DeepAgent construction smoke checks."""

from __future__ import annotations

from dataclasses import replace

from ops_pilot.agent.factory import create_agent_runtime_async
from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.config.settings import load_settings
from ops_pilot.tools.smoke_tools import get_smoke_tools


async def run() -> int:
    settings = replace(load_settings(), mcp=MCPConfig())
    runtime = await create_agent_runtime_async(settings=settings, extra_tools=get_smoke_tools())
    try:
        result = await runtime.graph.ainvoke(
            {"messages": [{"role": "user", "content": "Use add_numbers to compute 2 + 3."}]},
            config=runtime.runnable_config(protocol="chat", thread_id="smoke-agent"),
        )
        print(result)
        return 0
    finally:
        await runtime.aclose()


def main() -> int:
    import asyncio

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
