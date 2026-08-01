"""Minimal mapping helpers between A2A-ish payloads and DeepAgent inputs."""

from __future__ import annotations

from typing import Any


def text_to_agent_input(text: str) -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": text}]}


def extract_text(payload: Any) -> str:
    """Extract best-effort text from a future official A2A message payload."""

    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("text"), str):
            return payload["text"]
        message = payload.get("message")
        if isinstance(message, dict):
            parts = message.get("parts") or []
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    return part["text"]
    raise ValueError("Unable to extract text from A2A payload.")


def extract_agent_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            content = getattr(last, "content", None)
            if content is not None:
                return str(content)
            if isinstance(last, dict) and "content" in last:
                return str(last["content"])
        if "output" in result:
            return str(result["output"])
    content = getattr(result, "content", None)
    if content is not None:
        return str(content)
    return str(result)

