"""Normalize LangGraph results with LangChain's message API."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage, convert_to_messages


def extract_result_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        if (structured_response := result.get("structured_response")) is not None:
            if callable(model_dump_json := getattr(structured_response, "model_dump_json", None)):
                return str(model_dump_json())
            if isinstance(structured_response, (dict, list)):
                return json.dumps(structured_response, ensure_ascii=False, default=str)
            return str(structured_response)
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            return _message_text(messages[-1])
        for key in ("output", "content"):
            if (value := result.get(key)) is not None:
                return str(value)
    return _message_text(result)


def _message_text(message: Any) -> str:
    if isinstance(message, BaseMessage):
        return str(message.text)
    try:
        return str(convert_to_messages([message])[0].text)
    except (NotImplementedError, TypeError, ValueError):
        return str(message)
