"""Adapter helpers shared by the Dynatrace and Kibana source adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


class ToolRegistry:
    """Look up runtime-loaded MCP tools by name.

    MCP tools are loaded dynamically at startup (``mcp_registry.tools``), so the
    correlation nodes cannot import them. This wraps the loaded list and lets a
    node fetch a tool by name, returning ``None`` when it is absent (the source
    then degrades to a declared ``gap`` rather than crashing).
    """

    def __init__(self, tools: Sequence[Any]):
        self._by_name = {getattr(tool, "name", ""): tool for tool in tools}

    def get(self, name: str) -> Any | None:
        return self._by_name.get(name)

    def has(self, name: str) -> bool:
        return name in self._by_name

    def first(self, *names: str) -> Any | None:
        """Return the first available tool among ``names`` (name variants)."""

        for name in names:
            tool = self._by_name.get(name)
            if tool is not None:
                return tool
        return None


async def invoke_tool(tool: Any, args: Mapping[str, Any]) -> Any:
    """Invoke a LangChain tool with a proper ToolCall envelope.

    The storyline workflow calls MCP tools from inside another agent tool. Passing
    only the raw args makes LangChain return raw content blocks to callbacks;
    passing a ToolCall id lets LangChain normalize results into ToolMessage.
    """

    tool_input = _tool_call_input(tool, args)
    if hasattr(tool, "ainvoke"):
        return await tool.ainvoke(tool_input)
    return tool.invoke(tool_input)


def _tool_call_input(tool: Any, args: Mapping[str, Any]) -> dict[str, Any]:
    name = str(getattr(tool, "name", "tool") or "tool")
    return {
        "name": name,
        "args": dict(args),
        "id": f"storyline-{name}-{uuid4().hex}",
        "type": "tool_call",
    }


def parse_tool_payload(result: Any) -> Any:
    """MCP tools often return a JSON string (or content list). Parse to data."""

    if isinstance(result, (dict, list)):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except (json.JSONDecodeError, ValueError):
            return result
    # langchain ToolMessage-like content.
    content = getattr(result, "content", None)
    if content is not None and content is not result:
        return parse_tool_payload(content)
    return result


def to_epoch_ms(value: Any) -> int | None:
    """Normalize a timestamp (epoch ms int, epoch s, or ISO8601) to epoch ms."""

    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # Heuristic: > 1e12 is already ms; else treat as seconds.
        return int(value if value > 1e12 else value * 1000)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return to_epoch_ms(int(text))
        try:
            # Support trailing Z (UTC) which fromisoformat handles from 3.11.
            normalized = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            return None
    return None


def as_list(payload: Any, *keys: str) -> list[Any]:
    """Extract a list from a payload that may be a list or a wrapper dict."""

    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []
