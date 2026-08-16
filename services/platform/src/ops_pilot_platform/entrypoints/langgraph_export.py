"""Lazy graph export owned by the LangGraph server entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.runnables import RunnableConfig
from ops_pilot.agent.runtime import build_agent_runtime

from ops_pilot_platform.entrypoints.langgraph import build_langgraph_runtime_spec


@asynccontextmanager
async def graph(config: RunnableConfig) -> AsyncIterator[Any]:
    """Build one graph per LangGraph execution context and release its resources."""

    del config
    runtime = await build_agent_runtime(build_langgraph_runtime_spec())
    try:
        yield runtime.graph
    finally:
        await runtime.aclose()
