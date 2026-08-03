"""Agent middleware used by the shared DeepAgent runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage


class NormalizeSystemMessagesMiddleware(AgentMiddleware):
    """Keep all system instructions in the request-level system message.

    Anthropic Bedrock rejects message arrays that contain multiple non-consecutive
    system messages. Some integrations can add system instructions after the
    initial prompt, so normalize right before the model call.
    """

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(_normalize_system_messages(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(_normalize_system_messages(request))


def _normalize_system_messages(request: ModelRequest) -> ModelRequest:
    system_messages: list[SystemMessage] = []
    if request.system_message is not None:
        system_messages.append(request.system_message)

    remaining_messages = []
    for message in request.messages:
        if isinstance(message, SystemMessage):
            system_messages.append(message)
        else:
            remaining_messages.append(message)

    if not system_messages:
        return request

    normalized_system_message = SystemMessage(content=_join_system_contents(system_messages))
    if normalized_system_message == request.system_message and remaining_messages == request.messages:
        return request
    return request.override(system_message=normalized_system_message, messages=remaining_messages)


def _join_system_contents(messages: list[SystemMessage]) -> str:
    return "\n\n".join(_content_to_text(message.content) for message in messages if message.content)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_content_block_to_text(block) for block in content).strip()
    return str(content)


def _content_block_to_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        text = block.get("text") or block.get("content")
        return text if isinstance(text, str) else str(block)
    return str(block)
