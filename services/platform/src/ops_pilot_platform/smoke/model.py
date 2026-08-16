"""Developer smoke checks for SAP model integration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ops_pilot.models.factory import create_chat_model
from ops_pilot.runtime.spec import ModelSpec

from ops_pilot_platform.smoke.tools import get_smoke_tools


@dataclass(frozen=True)
class SmokeResult:
    name: str
    ok: bool
    detail: str


def smoke_model_invocation(
    model: ModelSpec,
    *,
    prompt: str = "Reply with exactly: ok",
) -> SmokeResult:
    chat_model = create_chat_model(model)
    try:
        response = chat_model.invoke(prompt)
    except Exception as exc:  # noqa: BLE001
        return SmokeResult("model.invoke", False, repr(exc))
    return SmokeResult("model.invoke", True, _summarize_response(response))


def smoke_bind_tools(model: ModelSpec) -> SmokeResult:
    chat_model = create_chat_model(model)
    try:
        bound = chat_model.bind_tools(get_smoke_tools())
    except Exception as exc:  # noqa: BLE001
        return SmokeResult("model.bind_tools", False, repr(exc))
    return SmokeResult("model.bind_tools", True, type(bound).__name__)


async def smoke_model_ainvocation(
    model: ModelSpec,
    *,
    prompt: str = "Reply with exactly: ok",
) -> SmokeResult:
    chat_model = create_chat_model(model)
    try:
        response = await chat_model.ainvoke(prompt)
    except Exception as exc:  # noqa: BLE001
        return SmokeResult("model.ainvoke", False, repr(exc))
    return SmokeResult("model.ainvoke", True, _summarize_response(response))


def smoke_invoke(model: ModelSpec, prompt: str = "Reply with OK.") -> str:
    result = smoke_model_invocation(model, prompt=prompt)
    if not result.ok:
        raise RuntimeError(result.detail)
    return result.detail


def run_smoke_checks(checks: Sequence[Callable[[], SmokeResult]]) -> list[SmokeResult]:
    return [check() for check in checks]


def _summarize_response(response: Any) -> str:
    content = getattr(response, "content", response)
    text = str(content).replace("\n", " ").strip()
    return text[:200]
