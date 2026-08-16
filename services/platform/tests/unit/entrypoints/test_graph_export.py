from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_graph_export_initializes_runtime_only_inside_factory(monkeypatch) -> None:
    import ops_pilot.agent.runtime as runtime_module

    calls: list[object] = []
    runtime = SimpleNamespace(graph=object(), aclose=_async_recorder(calls, "closed"))

    async def fake_build_agent_runtime(*_: object, **__: object):
        calls.append("built")
        return runtime

    monkeypatch.setattr(runtime_module, "build_agent_runtime", fake_build_agent_runtime)
    sys.modules.pop("ops_pilot_platform.entrypoints.langgraph_export", None)

    module = importlib.import_module("ops_pilot_platform.entrypoints.langgraph_export")

    assert calls == []
    async with module.graph({}) as exported_graph:
        assert exported_graph is runtime.graph
        assert calls == ["built"]
    assert calls == ["built", "closed"]


def _async_recorder(calls: list[object], value: object):
    async def record() -> None:
        calls.append(value)

    return record
