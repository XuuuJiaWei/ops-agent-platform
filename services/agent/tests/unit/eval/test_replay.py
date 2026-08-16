from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops_pilot.eval import replay
from ops_pilot.eval.dataset import EvalDatasetError
from ops_pilot.eval.runner import _extra_tools_for_cases


def _write_fixture(directory: Path, case_id: str, *, metric_value: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{case_id}.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "case_id": case_id,
                "origin": "test",
                "captured_at": "2026-08-16T00:00:00Z",
                "tools": {
                    "search_traces": {"service": case_id},
                    "query": {"value": metric_value},
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_replay_tool_requires_active_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(replay, "REPLAY_FIXTURE_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="without an active replay case"):
        await replay.query.ainvoke({"query": "up"})


@pytest.mark.asyncio
async def test_replay_tool_returns_bound_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(replay, "REPLAY_FIXTURE_DIR", tmp_path)
    _write_fixture(tmp_path, "case-a", metric_value=42)

    token = replay.activate_replay_case("case-a")
    try:
        result = json.loads(await replay.query.ainvoke({"query": "process_cpu_usage"}))
    finally:
        replay.reset_replay_case(token)

    assert result["replay"] is True
    assert result["case_id"] == "case-a"
    assert result["arguments"]["query"] == "process_cpu_usage"
    assert result["data"]["value"] == 42


@pytest.mark.asyncio
async def test_replay_context_is_isolated_between_concurrent_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(replay, "REPLAY_FIXTURE_DIR", tmp_path)
    _write_fixture(tmp_path, "case-a", metric_value=11)
    _write_fixture(tmp_path, "case-b", metric_value=22)

    async def invoke(case_id: str) -> tuple[str, int]:
        token = replay.activate_replay_case(case_id)
        try:
            await asyncio.sleep(0)
            payload = json.loads(await replay.query.ainvoke({"query": "memory"}))
            return payload["case_id"], payload["data"]["value"]
        finally:
            replay.reset_replay_case(token)

    assert list(await asyncio.gather(invoke("case-a"), invoke("case-b"))) == [
        ("case-a", 11),
        ("case-b", 22),
    ]


def test_replay_cases_get_reduced_local_tool_surface() -> None:
    cases = (SimpleNamespace(category="diagnosis", source="replay"),)

    tools = _extra_tools_for_cases(cases)

    assert {tool.name for tool in tools} == {"query", "search_traces"}


def test_replay_cases_cannot_mix_with_live_sources() -> None:
    cases = (
        SimpleNamespace(category="diagnosis", source="replay"),
        SimpleNamespace(category="diagnosis", source="synthetic"),
    )

    with pytest.raises(EvalDatasetError, match="Replay cases must run separately"):
        _extra_tools_for_cases(cases)
