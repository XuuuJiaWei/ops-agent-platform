from langchain_core.messages import ToolMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from ops_pilot.reliability.serde import ExecutionValueCodec


def test_execution_value_codec_round_trips_tool_message() -> None:
    codec = ExecutionValueCodec()
    value = ToolMessage(
        content="HTTP 503 Service Unavailable",
        tool_call_id="call-503",
        status="error",
        artifact={"structured_content": {"status": 503}},
    )

    restored = codec.loads_typed(codec.dumps_typed(value))

    assert isinstance(restored, ToolMessage)
    assert restored.content == value.content
    assert restored.tool_call_id == value.tool_call_id
    assert restored.status == value.status
    assert restored.artifact == value.artifact


def test_execution_value_codec_reads_legacy_jsonplus_tool_message() -> None:
    legacy = JsonPlusSerializer(pickle_fallback=False)
    value = ToolMessage(content="cached", tool_call_id="call-legacy")

    restored = ExecutionValueCodec().loads_typed(legacy.dumps_typed(value))

    assert isinstance(restored, ToolMessage)
    assert restored.content == "cached"
