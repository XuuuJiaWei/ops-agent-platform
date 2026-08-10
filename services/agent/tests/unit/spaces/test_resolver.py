from datetime import timedelta

import pytest

from ops_pilot.spaces.models import (
    CardBinding,
    CardContent,
    CardDraft,
    CardType,
    KpiMetric,
    RefreshStatus,
    SpaceCard,
    utc_now,
)
from ops_pilot.spaces.repository import MemorySpaceRepository
from ops_pilot.spaces.resolver import CardResolver, _is_due


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


@pytest.mark.asyncio
async def test_resolve_direct_shape_without_mapping() -> None:
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="ShapeTool", refresh_mode="interval", interval_ms=15_000)
    space_id, card_id = await _seed_live_card(repository, _live_kpi(binding))
    tool = _FakeTool("ShapeTool", result={"metrics": [{"label": "Count", "value": 42}]})

    await _resolver(repository, [tool]).resolve_card(space_id, (await repository.get_space(space_id)).cards[0])

    card = (await repository.get_space(space_id)).cards[0]
    assert card.refresh_status == RefreshStatus.FRESH
    assert card.content.metrics[0].value == 42
    assert card.last_error is None


@pytest.mark.asyncio
async def test_resolve_with_jmespath_mapping() -> None:
    repository = MemorySpaceRepository()
    binding = CardBinding(
        source_tool="CountTool",
        mapping={"metrics": "[{label: 'Docs', value: to_string(count)}]"},
        refresh_mode="interval",
        interval_ms=15_000,
    )
    space_id, card_id = await _seed_live_card(repository, _live_kpi(binding))
    tool = _FakeTool("CountTool", result={"count": 128})

    await _resolver(repository, [tool]).resolve_card(space_id, (await repository.get_space(space_id)).cards[0])

    card = (await repository.get_space(space_id)).cards[0]
    assert card.refresh_status == RefreshStatus.FRESH
    assert card.content.metrics[0].label == "Docs"
    assert card.content.metrics[0].value == "128"


@pytest.mark.asyncio
async def test_resolve_rejects_hitl_tool() -> None:
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="DangerTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_kpi(binding))
    tool = _FakeTool("DangerTool", result={"metrics": []})

    await _resolver(repository, [tool], hitl=frozenset({"DangerTool"})).resolve_card(
        space_id, (await repository.get_space(space_id)).cards[0]
    )

    card = (await repository.get_space(space_id)).cards[0]
    assert card.refresh_status == RefreshStatus.ERROR
    assert "binding_forbidden_tool" in (card.last_error or "")
    assert tool.calls == []  # never invoked


@pytest.mark.asyncio
async def test_resolve_rejects_unknown_tool() -> None:
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="MissingTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_kpi(binding))

    await _resolver(repository, []).resolve_card(space_id, (await repository.get_space(space_id)).cards[0])

    card = (await repository.get_space(space_id)).cards[0]
    assert card.refresh_status == RefreshStatus.ERROR
    assert "binding_unknown_tool" in (card.last_error or "")


@pytest.mark.asyncio
async def test_resolve_preserves_last_good_on_tool_error() -> None:
    repository = MemorySpaceRepository()
    binding = CardBinding(source_tool="FlakyTool", refresh_mode="interval", interval_ms=15_000)
    space_id, _ = await _seed_live_card(repository, _live_kpi(binding, value=7))
    tool = _FakeTool("FlakyTool", error=RuntimeError("boom"))

    await _resolver(repository, [tool]).resolve_card(space_id, (await repository.get_space(space_id)).cards[0])

    card = (await repository.get_space(space_id)).cards[0]
    assert card.refresh_status == RefreshStatus.ERROR
    assert "boom" in (card.last_error or "")
    assert card.content.metrics[0].value == 7  # last-good content retained


@pytest.mark.asyncio
async def test_resolve_flags_invalid_mapped_content() -> None:
    repository = MemorySpaceRepository()
    # KPI requires non-empty metrics; mapping produces an empty list.
    binding = CardBinding(
        source_tool="EmptyTool",
        mapping={"metrics": "missing"},
        refresh_mode="interval",
        interval_ms=15_000,
    )
    space_id, _ = await _seed_live_card(repository, _live_kpi(binding))
    tool = _FakeTool("EmptyTool", result={"other": 1})

    await _resolver(repository, [tool]).resolve_card(space_id, (await repository.get_space(space_id)).cards[0])

    card = (await repository.get_space(space_id)).cards[0]
    assert card.refresh_status == RefreshStatus.ERROR
    assert "binding_invalid" in (card.last_error or "")


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
