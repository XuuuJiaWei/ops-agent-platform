from langchain_core.messages import AIMessage

from ops_pilot.agent.results import extract_result_text


def test_extract_result_text_uses_standard_message_content_blocks() -> None:
    result = {
        "messages": [
            AIMessage(
                content=[
                    {"type": "text", "text": "first"},
                    {"type": "image_url", "image_url": {"url": "https://example.test/image.png"}},
                    {"type": "text", "text": "second"},
                ]
            )
        ]
    }

    assert extract_result_text(result) == "firstsecond"
