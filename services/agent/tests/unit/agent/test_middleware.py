from typing import Any, cast

from langchain.agents.middleware import ModelRequest
from langchain_core.messages import HumanMessage, SystemMessage

from ops_pilot.agent.middleware import _normalize_system_messages


def test_normalize_system_messages_moves_all_system_content_to_request_prompt():
    request = ModelRequest(
        model=cast(Any, None),
        system_message=SystemMessage(content="base instructions"),
        messages=[
            HumanMessage(content="hello"),
            SystemMessage(content="late instructions"),
            HumanMessage(content="continue"),
        ],
    )

    normalized = _normalize_system_messages(request)

    assert normalized.system_message is not None
    assert normalized.system_message.content == "base instructions\n\nlate instructions"
    assert [message.content for message in normalized.messages] == ["hello", "continue"]
