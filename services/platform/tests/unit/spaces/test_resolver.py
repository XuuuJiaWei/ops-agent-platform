from datetime import timedelta

import pytest
from langchain_core.messages import ToolMessage

from ops_pilot_platform.web.spaces.models import (
    CardBinding,
    CardContent,
    CardDraft,
    CardType,
    KpiMetric,
    RefreshStatus,
    SpaceCard,
    utc_now,
)
from ops_pilot_platform.web.spaces.repository import MemorySpaceRepository
from ops_pilot_platform.web.spaces.resolver import MAX_RAW_SNAPSHOT_BYTES, CardResolver, _is_due


class _FakeTool:
    """Minimal stand-in for a LangChain BaseTool with a name + ainvoke."""

    def __init__(self, name: str, *, result=None, error: Exception | None = None) -> None:
        self.name = name
        self._result = result
        self._error = error
        self.calls: list[dict] = []

    async def ainvoke(self, params):
        self.calls.append(params)
        if self._error is not None:
            raise self._error
        return self._result


def _live_kpi(binding: CardBinding, *, value: int | None = None) -> CardDraft:
    metrics = [KpiMetric(label="Count", value=value)] if value is not None else []
    return CardDraft(
        type=CardType.KPI,
        title="Live count",
        content=CardContent(metrics=metrics),
        binding=binding,
    )


def _live_markdown(binding: CardBinding) -> CardDraft:
    return CardDraft(
        type=CardType.MARKDOWN,
        title="Live text",
        content=CardContent(),
        binding=binding,
    )


def _live_table(binding: CardBinding) -> CardDraft:
    return CardDraft(
        type=CardType.TABLE,
        title="Live table",
        content=CardContent(),
        binding=binding,
    )


async def _seed_live_card(repository: MemorySpaceRepository, draft: CardDraft) -> tuple[str, str]:
    space = await repository.create_space("Ops")
    space = await repository.add_card(space.id, draft)
    return space.id, space.cards[0].id


def _resolver(repository: MemorySpaceRepository, tools, hitl=frozenset()) -> CardResolver:
    return CardResolver(
        repository=repository,
        tools_by_name={tool.name: tool for tool in tools},
        hitl_tools=hitl,
    )


async def _only_card(repository: MemorySpaceRepository, space_id: str) -> SpaceCard:
    return (await repository.get_space(space_id)).cards[0]


@pytest.mark.asyncio
async def test_resolve_stores_structured_snapshot() -> None:
    # The resolver never shapes data: a structured tool response is stored raw.
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="ShapeTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_kpi(binding))
    tool = _FakeTool("ShapeTool", result={"metrics": [{"label": "Count", "value": 42}]})

    await _resolver(repository, [tool]).resolve_card(space_id, await _only_card(repository, space_id))

    card = await _only_card(repository, space_id)
    assert card.refresh_status == RefreshStatus.FRESH
    assert card.raw_snapshot == {"metrics": [{"label": "Count", "value": 42}]}
    assert card.last_error is None


@pytest.mark.asyncio
async def test_resolve_stores_text_snapshot_verbatim() -> None:
    # Free-form text (e.g. a Prometheus instant vector) is stored as-is; the
    # frontend transform is responsible for parsing it.
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="PromTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_table(binding))
    text = 'kubelet_running_pods{k8s_node_name="ip-a"} => 21 @[1786429567.161]'
    tool = _FakeTool("PromTool", result=text)

    await _resolver(repository, [tool]).resolve_card(space_id, await _only_card(repository, space_id))

    card = await _only_card(repository, space_id)
    assert card.refresh_status == RefreshStatus.FRESH
    assert card.raw_snapshot == text


@pytest.mark.asyncio
async def test_resolve_prefers_structured_content_artifact() -> None:
    # A spec-compliant server populates structuredContent; the adapter surfaces
    # it as a ToolMessage artifact, which must win over the text content blocks.
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="StructuredTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_kpi(binding))
    message = ToolMessage(
        content=[{"type": "text", "text": "human readable, ignored"}],
        artifact={"structured_content": {"count": 512}},
        tool_call_id="card-resolver",
    )
    tool = _FakeTool("StructuredTool", result=message)

    await _resolver(repository, [tool]).resolve_card(space_id, await _only_card(repository, space_id))

    card = await _only_card(repository, space_id)
    assert card.refresh_status == RefreshStatus.FRESH
    assert card.raw_snapshot == {"count": 512}


@pytest.mark.asyncio
async def test_resolve_decodes_json_text_content_blocks() -> None:
    # No structuredContent: the adapter returns text blocks whose text is a JSON
    # envelope (the Prometheus MCP shape). The resolver decodes it, then stores
    # the decoded object as the raw snapshot.
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="PromTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_markdown(binding))
    message = ToolMessage(
        content=[{"type": "text", "text": '{"result": "up{job=\\"api\\"} => 1 @[ts]", "warnings": null}'}],
        artifact=None,
        tool_call_id="card-resolver",
    )
    tool = _FakeTool("PromTool", result=message)

    await _resolver(repository, [tool]).resolve_card(space_id, await _only_card(repository, space_id))

    card = await _only_card(repository, space_id)
    assert card.refresh_status == RefreshStatus.FRESH
    assert card.raw_snapshot == {"result": 'up{job="api"} => 1 @[ts]', "warnings": None}


@pytest.mark.asyncio
async def test_resolve_rejects_hitl_tool() -> None:
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="DangerTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_kpi(binding))
    tool = _FakeTool("DangerTool", result={"metrics": []})

    await _resolver(repository, [tool], hitl=frozenset({"DangerTool"})).resolve_card(
        space_id, await _only_card(repository, space_id)
    )

    card = await _only_card(repository, space_id)
    assert card.refresh_status == RefreshStatus.ERROR
    assert "binding_forbidden_tool" in (card.last_error or "")
    assert tool.calls == []  # never invoked


@pytest.mark.asyncio
async def test_resolve_rejects_unknown_tool() -> None:
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="MissingTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_kpi(binding))

    await _resolver(repository, []).resolve_card(space_id, await _only_card(repository, space_id))

    card = await _only_card(repository, space_id)
    assert card.refresh_status == RefreshStatus.ERROR
    assert "binding_unknown_tool" in (card.last_error or "")


@pytest.mark.asyncio
async def test_resolve_preserves_last_good_snapshot_on_tool_error() -> None:
    # A successful refresh stores a snapshot; a later failure keeps it and only
    # flips the status/last_error.
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="FlakyTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_markdown(binding))

    good = _FakeTool("FlakyTool", result={"value": 7})
    await _resolver(repository, [good]).resolve_card(space_id, await _only_card(repository, space_id))
    assert (await _only_card(repository, space_id)).raw_snapshot == {"value": 7}

    broken = _FakeTool("FlakyTool", error=RuntimeError("boom"))
    await _resolver(repository, [broken]).resolve_card(space_id, await _only_card(repository, space_id))

    card = await _only_card(repository, space_id)
    assert card.refresh_status == RefreshStatus.ERROR
    assert "boom" in (card.last_error or "")
    assert card.raw_snapshot == {"value": 7}  # last-good snapshot retained


@pytest.mark.asyncio
async def test_resolve_flags_oversized_snapshot() -> None:
    # A snapshot larger than the byte cap is rejected before it can bloat the row.
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="FirehoseTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_markdown(binding))
    tool = _FakeTool("FirehoseTool", result={"data": "x" * (MAX_RAW_SNAPSHOT_BYTES + 1)})

    await _resolver(repository, [tool]).resolve_card(space_id, await _only_card(repository, space_id))

    card = await _only_card(repository, space_id)
    assert card.refresh_status == RefreshStatus.ERROR
    assert "binding_snapshot_too_large" in (card.last_error or "")
    assert card.raw_snapshot is None  # nothing stored


@pytest.mark.asyncio
async def test_resolve_surfaces_tool_error_message() -> None:
    # An MCP isError result arrives as a ToolMessage with status='error'.
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="BrokenTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_markdown(binding))
    message = ToolMessage(
        content=[{"type": "text", "text": "query parse error"}],
        status="error",
        tool_call_id="card-resolver",
    )
    tool = _FakeTool("BrokenTool", result=message)

    await _resolver(repository, [tool]).resolve_card(space_id, await _only_card(repository, space_id))

    card = await _only_card(repository, space_id)
    assert card.refresh_status == RefreshStatus.ERROR
    assert "binding_source_error" in (card.last_error or "")
    assert "query parse error" in (card.last_error or "")


def test_is_due_respects_interval_and_mode() -> None:
    now = utc_now()
    interval = CardBinding(source_tool="T", refresh_mode="interval", interval_ms=30_000)
    manual = CardBinding(source_tool="T", refresh_mode="manual")

    def _card(binding: CardBinding, last_refreshed_at) -> SpaceCard:
        return SpaceCard(
            type=CardType.KPI,
            title="Live count",
            content=CardContent(),
            binding=binding,
            id="card-1",
            created_at=now,
            updated_at=now,
            last_refreshed_at=last_refreshed_at,
        )

    assert _is_due(_card(interval, None), now) is True
    assert _is_due(_card(interval, now), now) is False
    assert _is_due(_card(interval, now - timedelta(seconds=60)), now) is True
    assert _is_due(_card(manual, None), now) is False
