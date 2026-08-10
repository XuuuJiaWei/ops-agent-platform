"""Versioned persistence codec for reliable tool execution values."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

_TYPE_KEY = "__ops_pilot_execution_value__"
_MESSAGE_TYPE = "langchain_message"
_VERSION = 1


class ExecutionValueCodec:
    """Keep framework message objects out of the execution journal schema."""

    def __init__(self) -> None:
        self._serde = JsonPlusSerializer(pickle_fallback=False)

    def dumps_typed(self, value: Any) -> tuple[str, bytes]:
        return self._serde.dumps_typed(self._to_storage(value))

    def loads_typed(self, value: tuple[str, bytes]) -> Any:
        return self._from_storage(self._serde.loads_typed(value))

    @staticmethod
    def _to_storage(value: Any) -> Any:
        if isinstance(value, BaseMessage):
            return {
                _TYPE_KEY: _MESSAGE_TYPE,
                "version": _VERSION,
                "value": message_to_dict(value),
            }
        return value

    @staticmethod
    def _from_storage(value: Any) -> Any:
        if not isinstance(value, dict) or value.get(_TYPE_KEY) != _MESSAGE_TYPE:
            return value
        if value.get("version") != _VERSION or not isinstance(value.get("value"), dict):
            raise ValueError("Unsupported persisted LangChain message envelope.")
        return messages_from_dict([value["value"]])[0]
