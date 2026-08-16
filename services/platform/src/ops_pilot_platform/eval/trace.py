"""Trace helpers for eval runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ops_pilot.agent.results import extract_result_text


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    args: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "args": self.args}


@dataclass(frozen=True)
class AgentTrace:
    final_text: str
    tool_calls: tuple[ToolCallRecord, ...] = field(default_factory=tuple)
    steps: int = 0
    raw_messages: tuple[Any, ...] = field(default_factory=tuple)
    latency_s: float = 0.0

    def as_output(self) -> dict[str, Any]:
        return {
            "final_text": self.final_text,
            "tool_calls": [tool_call.as_dict() for tool_call in self.tool_calls],
            "steps": self.steps,
            "latency_s": self.latency_s,
            "error": None,
            "recursion_limit_hit": False,
        }


def build_agent_trace(result: Any, *, latency_s: float) -> AgentTrace:
    messages = _result_messages(result)
    return AgentTrace(
        final_text=extract_result_text(result),
        tool_calls=_extract_tool_calls(messages),
        steps=len(messages),
        raw_messages=tuple(messages),
        latency_s=latency_s,
    )


def _result_messages(result: Any) -> list[Any]:
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list):
            return messages
    return []


def _extract_tool_calls(messages: list[Any]) -> tuple[ToolCallRecord, ...]:
    calls: list[ToolCallRecord] = []
    for message in messages:
        raw_tool_calls = _message_tool_calls(message)
        if not raw_tool_calls:
            continue
        for raw_call in raw_tool_calls:
            parsed = _parse_tool_call(raw_call)
            if parsed is not None:
                calls.append(parsed)
    return tuple(calls)


def _message_tool_calls(message: Any) -> Any:
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return tool_calls
    if isinstance(message, dict):
        return message.get("tool_calls")
    return None


def _parse_tool_call(raw_call: Any) -> ToolCallRecord | None:
    if isinstance(raw_call, Mapping):
        name = raw_call.get("name")
        args = raw_call.get("args", raw_call.get("arguments"))
        function = raw_call.get("function")
        if not name and isinstance(function, Mapping):
            name = function.get("name")
            args = args if args is not None else function.get("arguments")
        if name:
            return ToolCallRecord(name=str(name), args=args)
        return None
    name = getattr(raw_call, "name", None)
    if not name:
        function = getattr(raw_call, "function", None)
        name = getattr(function, "name", None)
    if not name:
        return None
    args = getattr(raw_call, "args", None)
    if args is None:
        args = getattr(raw_call, "arguments", None)
    return ToolCallRecord(name=str(name), args=args)
