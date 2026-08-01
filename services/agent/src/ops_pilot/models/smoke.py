"""Developer smoke checks for SAP model integration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ops_pilot.config.settings import Settings, load_settings
from ops_pilot.models.sap_genai import create_chat_model
from ops_pilot.tools.smoke_tools import get_smoke_tools


@dataclass(frozen=True)
class SmokeResult:
    name: str
    ok: bool
    detail: str


def smoke_model_invocation(
    settings: Settings | None = None,
    *,
    prompt: str = "Reply with exactly: ok",
) -> SmokeResult:
    model = create_chat_model(settings or load_settings())
    try:
        response = model.invoke(prompt)
    except Exception as exc:  # noqa: BLE001
        return SmokeResult("model.invoke", False, repr(exc))
    return SmokeResult("model.invoke", True, _summarize_response(response))


def smoke_bind_tools(settings: Settings | None = None) -> SmokeResult:
    model = create_chat_model(settings or load_settings())
    try:
        bound = model.bind_tools(get_smoke_tools())
    except Exception as exc:  # noqa: BLE001
        return SmokeResult("model.bind_tools", False, repr(exc))
    return SmokeResult("model.bind_tools", True, type(bound).__name__)


async def smoke_model_ainvocation(
    settings: Settings | None = None,
    *,
    prompt: str = "Reply with exactly: ok",
) -> SmokeResult:
    model = create_chat_model(settings or load_settings())
    try:
        response = await model.ainvoke(prompt)
    except Exception as exc:  # noqa: BLE001
        return SmokeResult("model.ainvoke", False, repr(exc))
    return SmokeResult("model.ainvoke", True, _summarize_response(response))


def smoke_invoke(settings: Settings, prompt: str = "Reply with OK.") -> str:
    result = smoke_model_invocation(settings, prompt=prompt)
    if not result.ok:
        raise RuntimeError(result.detail)
    return result.detail


def run_smoke_checks(checks: Sequence[Callable[[], SmokeResult]]) -> list[SmokeResult]:
    return [check() for check in checks]


def _summarize_response(response: Any) -> str:
    content = getattr(response, "content", response)
    text = str(content).replace("\n", " ").strip()
    return text[:200]

