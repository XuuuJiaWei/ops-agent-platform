import pytest

from ops_pilot.spaces.models import (
    CardBinding,
    CardContent,
    CardDraft,
    CardSize,
    CardType,
    KpiMetric,
    RefreshStatus,
)
from ops_pilot.spaces.repository import (
    CardNotFoundError,
    InvalidCardOrderError,
    MemorySpaceRepository,
    SpaceNotFoundError,
)


def _kpi(title: str, value: int) -> CardDraft:
    return CardDraft(
        type=CardType.KPI,
        title=title,
        content=CardContent(metrics=[KpiMetric(label="Incidents", value=value)]),
    )


@pytest.mark.asyncio
async def test_memory_repository_supports_complete_space_card_lifecycle() -> None:
    repository = MemorySpaceRepository()

    created = await repository.create_space("Operations", "Live service health")
    with_first = await repository.add_card(created.id, _kpi("Open incidents", 7))
    with_second = await repository.add_card(created.id, _kpi("Resolved today", 12))
    first_id, second_id = [card.id for card in with_second.cards]

    updated = await repository.update_card(
        created.id,
        first_id,
        content=CardContent(metrics=[KpiMetric(label="Open incidents", value=5)]),
        subtitle="Across production",
    )
    renamed = await repository.rename_card(created.id, first_id, "Active incidents")
    resized = await repository.resize_card(created.id, first_id, CardSize.SMALL)
    reordered = await repository.reorder_cards(created.id, [second_id, first_id])
    removed = await repository.remove_card(created.id, second_id)

    assert with_first.version == 2
    assert updated.cards[0].content.metrics[0].value == 5
    assert updated.cards[0].subtitle == "Across production"
    assert renamed.cards[0].title == "Active incidents"
    assert resized.cards[0].size == CardSize.SMALL
    assert [card.id for card in reordered.cards] == [second_id, first_id]
    assert [card.id for card in removed.cards] == [first_id]
    assert (await repository.list_spaces())[0].card_count == 1


@pytest.mark.asyncio
async def test_memory_repository_reports_invalid_targets_and_order() -> None:
    repository = MemorySpaceRepository()
    space = await repository.create_space("Operations")
    space = await repository.add_card(space.id, _kpi("Open incidents", 7))

    with pytest.raises(SpaceNotFoundError):
        await repository.get_space("missing")
    with pytest.raises(CardNotFoundError):
        await repository.rename_card(space.id, "missing", "No card")
    with pytest.raises(InvalidCardOrderError):
        await repository.reorder_cards(space.id, [])


def _live_kpi() -> CardDraft:
    return CardDraft(
        type=CardType.KPI,
        title="Live count",
        content=CardContent(),
        binding=CardBinding(source_tool="CountTool", refresh_mode="interval", interval_ms=30_000),
    )


@pytest.mark.asyncio
async def test_apply_refresh_updates_content_without_bumping_version() -> None:
    repository = MemorySpaceRepository()
    space = await repository.create_space("Operations")
    space = await repository.add_card(space.id, _live_kpi())
    card_id = space.cards[0].id
    version_before = space.version

    await repository.apply_refresh(
        space.id,
        card_id,
        content=CardContent(metrics=[KpiMetric(label="Count", value=99)]),
        status=RefreshStatus.FRESH,
        last_error=None,
        last_refreshed_at=None,
    )

    refreshed = await repository.get_space(space.id)
    assert refreshed.version == version_before  # refresh must not inflate version
    assert refreshed.cards[0].content.metrics[0].value == 99
    assert refreshed.cards[0].refresh_status == RefreshStatus.FRESH


@pytest.mark.asyncio
async def test_list_live_cards_returns_only_bound_cards() -> None:
    repository = MemorySpaceRepository()
    space = await repository.create_space("Operations")
    await repository.add_card(space.id, _kpi("Static", 7))
    await repository.add_card(space.id, _live_kpi())

    live = await repository.list_live_cards()
    assert len(live) == 1
    live_space_id, live_card = live[0]
    assert live_space_id == space.id
    assert live_card.binding is not None
    assert live_card.binding.source_tool == "CountTool"
