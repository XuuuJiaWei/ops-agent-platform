import pytest

from ops_pilot.spaces import MemorySpaceRepository, build_space_tools

EXPECTED_TOOLS = {
    "render_ui",
    "create_space",
    "add_card_to_space",
    "update_card_in_space",
    "rename_card",
    "resize_card",
    "remove_card_from_space",
    "reorder_cards_in_space",
    "list_spaces",
    "get_space",
}


def _tool_map():
    return {tool.name: tool for tool in build_space_tools(MemorySpaceRepository())}


def _card_payload(value: int = 7) -> dict:
    return {
        "type": "kpi",
        "title": "Open incidents",
        "size": "small",
        "content": {"metrics": [{"label": "Incidents", "value": value}]},
    }


def test_space_tool_names_are_the_public_contract() -> None:
    assert set(_tool_map()) == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_space_tools_create_mutate_and_read_space() -> None:
    tools = _tool_map()
    created = await tools["create_space"].ainvoke({"name": "Operations", "description": "Live service health"})
    space_id = created["space"]["id"]

    added = await tools["add_card_to_space"].ainvoke({"space_id": space_id, "card": _card_payload()})
    card_id = added["space"]["cards"][0]["id"]
    updated = await tools["update_card_in_space"].ainvoke(
        {
            "space_id": space_id,
            "card_id": card_id,
            "content": {"metrics": [{"label": "Incidents", "value": 5}]},
            "subtitle": "Across production",
        }
    )
    listed = await tools["list_spaces"].ainvoke({})
    fetched = await tools["get_space"].ainvoke({"space_id": space_id})

    assert updated["space"]["cards"][0]["content"]["metrics"][0]["value"] == 5
    assert updated["space"]["cards"][0]["subtitle"] == "Across production"
    assert listed["spaces"][0]["card_count"] == 1
    assert fetched["space"]["id"] == space_id


@pytest.mark.asyncio
async def test_render_ui_is_transient_and_does_not_create_a_space() -> None:
    tools = _tool_map()

    rendered = await tools["render_ui"].ainvoke({"card": _card_payload()})
    listed = await tools["list_spaces"].ainvoke({})

    assert rendered["ok"] is True
    assert rendered["transient"] is True
    assert rendered["card"]["type"] == "kpi"
    assert listed["spaces"] == []


@pytest.mark.asyncio
async def test_tool_domain_errors_are_model_visible_results() -> None:
    tools = _tool_map()

    result = await tools["get_space"].ainvoke({"space_id": "missing"})

    assert result == {
        "ok": False,
        "error": {
            "code": "space_not_found",
            "message": "Space 'missing' was not found.",
        },
    }
