"""CLI entry point for DeepAgent construction smoke checks."""

from __future__ import annotations

from ops_pilot.agent.factory import create_agent_runtime_async


async def run() -> int:
    runtime = await create_agent_runtime_async()
    result = await runtime.graph.ainvoke(
        {"messages": [{"role": "user", "content": "Use add_numbers to compute 2 + 3."}]},
        config=runtime.runnable_config(protocol="chat", thread_id="smoke-agent"),
    )
    print(result)
    return 0


def main() -> int:
    import asyncio

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
