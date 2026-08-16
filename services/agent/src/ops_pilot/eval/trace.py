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
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    token_usage_available: bool = False

    def as_output(self) -> dict[str, Any]:
        return {
            "final_text": self.final_text,
            "tool_calls": [tool_call.as_dict() for tool_call in self.tool_calls],
            "steps": self.steps,
            "latency_s": self.latency_s,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "token_usage_available": self.token_usage_available,
            "error": None,
            "recursion_limit_hit": False,
        }


def build_agent_trace(result: Any, *, latency_s: float) -> AgentTrace:
    messages = _result_messages(result)
    input_tokens, output_tokens, total_tokens, token_usage_available = _extract_token_usage(messages)
    return AgentTrace(
        final_text=extract_result_text(result),
        tool_calls=_extract_tool_calls(messages),
        steps=len(messages),
        raw_messages=tuple(messages),
        latency_s=latency_s,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        token_usage_available=token_usage_available,
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


def _extract_token_usage(messages: list[Any]) -> tuple[int, int, int, bool]:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    available = False

    for message in messages:
        usage = _message_usage(message)
        if usage is None:
            continue
        available = True
        message_input = _usage_int(usage, "input_tokens", "prompt_tokens", "input_token_count")
        message_output = _usage_int(usage, "output_tokens", "completion_tokens", "output_token_count")
        message_total = _usage_int(usage, "total_tokens", "total_token_count")
        if message_total is None:
            message_total = (message_input or 0) + (message_output or 0)

        input_tokens += message_input or 0
        output_tokens += message_output or 0
        total_tokens += message_total

    return input_tokens, output_tokens, total_tokens, available


def _message_usage(message: Any) -> Mapping[str, Any] | None:
    usage = getattr(message, "usage_metadata", None)
    if not isinstance(usage, Mapping) and isinstance(message, Mapping):
        usage = message.get("usage_metadata")
    if isinstance(usage, Mapping):
        return usage

    response_metadata = getattr(message, "response_metadata", None)
    if not isinstance(response_metadata, Mapping) and isinstance(message, Mapping):
        response_metadata = message.get("response_metadata")
    if not isinstance(response_metadata, Mapping):
        return None

    for key in ("token_usage", "usage"):
        nested = response_metadata.get(key)
        if isinstance(nested, Mapping):
            return nested
    return None


def _usage_int(usage: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and value >= 0:
            return int(value)
    return None


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
