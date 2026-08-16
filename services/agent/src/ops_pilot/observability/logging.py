"""Structured local agent logs using LangChain's official middleware hooks."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.messages import AIMessage, ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command

from ops_pilot.errors import safe_exception_summary
from ops_pilot.runtime.spec import AgentLoggingSpec

logger = logging.getLogger("ops_pilot.agent.events")

_CORRELATION_FIELDS = (
    "assistant_id",
    "protocol",
    "thread_id",
    "run_id",
    "model_provider",
    "model_name",
)
_SECRET_FIELDS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "headers",
        "password",
        "secret",
        "secret_key",
        "token",
    }
)


@dataclass(frozen=True)
class AgentLoggingMiddleware(AgentMiddleware):
    """Log model and tool lifecycle events without retaining mutable run state."""

    spec: AgentLoggingSpec

    def __post_init__(self) -> None:
        logger.setLevel(self.spec.level)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        started = perf_counter()
        correlation = _correlation(request.runtime)
        _log(
            logging.INFO,
            "agent.model.started",
            **correlation,
            message_count=len(request.messages),
            tools=[_tool_name(item) for item in request.tools],
            tool_choice=request.tool_choice,
            response_format=type(request.response_format).__name__ if request.response_format is not None else None,
            model_settings=_safe_value(request.model_settings, self.spec.max_preview_chars),
        )
        try:
            response = await handler(request)
        except BaseException as error:
            _log(
                logging.ERROR,
                "agent.model.failed",
                **correlation,
                duration_ms=_duration_ms(started),
                error_type=type(error).__name__,
                error=safe_exception_summary(error),
            )
            raise

        messages = [message for message in response.result if isinstance(message, AIMessage)]
        tool_calls = [call for message in messages for call in message.tool_calls]
        event: dict[str, Any] = {
            **correlation,
            "duration_ms": _duration_ms(started),
            "response_messages": len(response.result),
            "tool_calls": [
                {
                    "name": call.get("name", "unknown"),
                    **(
                        {"args": _safe_value(call.get("args"), self.spec.max_preview_chars)}
                        if self.spec.payloads == "preview"
                        else {}
                    ),
                }
                for call in tool_calls
            ],
            "usage": _usage(messages),
            "structured_response": response.structured_response is not None,
            "finish_reasons": [
                message.response_metadata.get("finish_reason")
                for message in messages
                if message.response_metadata.get("finish_reason") is not None
            ],
        }
        if self.spec.payloads == "preview":
            event["content_preview"] = _preview(
                [message.content for message in messages if message.content],
                self.spec.max_preview_chars,
            )
        _log(logging.INFO, "agent.model.completed", **event)
        return response

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        started = perf_counter()
        name = str(request.tool_call.get("name", "unknown"))
        correlation = _correlation(request.runtime)
        event: dict[str, Any] = {**correlation, "tool_name": name}
        if self.spec.payloads == "preview":
            event["arguments"] = _safe_value(request.tool_call.get("args"), self.spec.max_preview_chars)
        _log(logging.INFO, "agent.tool.started", **event)
        try:
            result = await handler(request)
        except BaseException as error:
            _log(
                logging.ERROR,
                "agent.tool.failed",
                **correlation,
                tool_name=name,
                duration_ms=_duration_ms(started),
                error_type=type(error).__name__,
                error=safe_exception_summary(error),
            )
            raise

        completed: dict[str, Any] = {
            **correlation,
            "tool_name": name,
            "duration_ms": _duration_ms(started),
            "result_type": type(result).__name__,
        }
        if isinstance(result, ToolMessage):
            content = _text(result.content)
            completed.update(
                status=result.status,
                content_length=len(content),
            )
            if self.spec.payloads == "preview":
                completed["content_preview"] = _preview(content, self.spec.max_preview_chars)
        _log(logging.INFO, "agent.tool.completed", **completed)
        return result


def configure_runtime_logging(level: str = "INFO") -> None:
    """Give CLI hosts one concise stderr formatter without overriding host handlers."""

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.setLevel(level)
    for dependency in ("httpcore", "httpx"):
        logging.getLogger(dependency).setLevel(logging.WARNING)


def _log(level: int, event_name: str, **fields: Any) -> None:
    payload = {"event": event_name, **fields}
    logger.log(
        level,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
        extra={"event_name": event_name},
    )


def _correlation(runtime: Any) -> dict[str, Any]:
    config = getattr(runtime, "config", None)
    if not isinstance(config, Mapping):
        return {}
    metadata = config.get("metadata")
    if not isinstance(metadata, Mapping):
        return {}
    return {name: metadata[name] for name in _CORRELATION_FIELDS if metadata.get(name) not in (None, "")}


def _usage(messages: list[AIMessage]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for message in messages:
        for key, value in (message.usage_metadata or {}).items():
            if isinstance(value, int):
                totals[key] = totals.get(key, 0) + value
    return totals


def _tool_name(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("name", "unknown"))
    return str(getattr(value, "name", type(value).__name__))


def _safe_value(value: Any, limit: int) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]" if str(key).casefold() in _SECRET_FIELDS else _safe_value(item, limit)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, limit) for item in value[:50]]
    if isinstance(value, str):
        return _preview(value, limit)
    return value


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _preview(value: Any, limit: int) -> str:
    text = _text(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
