"""In-process resolver that replays card data bindings on a schedule.

A card may carry a :class:`~ops_pilot.spaces.models.CardBinding` describing how
to fetch its data (which registered read-only tool to call, with what params,
and how to map the response) instead of holding a static snapshot. This module
periodically re-runs those bindings and writes the result back onto the card —
without ever re-invoking the LLM.

Phase 1 scope: a single in-process asyncio loop, no Postgres lease, no separate
worker. Multi-worker safety is deferred to a later phase.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import jmespath
from jmespath.exceptions import JMESPathError

from ops_pilot.spaces.models import (
    REQUIRED_CONTENT_FIELD,
    CardContent,
    CardType,
    RefreshStatus,
    SpaceCard,
    utc_now,
)
from ops_pilot.spaces.repository import SpaceError, SpaceRepository

logger = logging.getLogger("uvicorn.error")


class BindingError(RuntimeError):
    """A binding could not be resolved; ``code`` classifies the failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CardResolver:
    """Periodically replay live-card bindings and write results back."""

    def __init__(
        self,
        *,
        repository: SpaceRepository,
        tools_by_name: Mapping[str, Any],
        hitl_tools: frozenset[str],
        poll_interval_s: float = 30.0,
        invoke_timeout_s: float = 30.0,
        max_concurrency: int = 4,
    ) -> None:
        self._repository = repository
        self._tools_by_name = tools_by_name
        self._hitl_tools = hitl_tools
        self._poll_interval_s = poll_interval_s
        self._invoke_timeout_s = invoke_timeout_s
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def run_forever(self) -> None:
        """Poll for due live cards and refresh them until cancelled."""

        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive: never let the loop die
                logger.exception("Card resolver tick failed")
            await asyncio.sleep(self._poll_interval_s)

    async def _tick(self) -> None:
        try:
            live_cards = await self._repository.list_live_cards()
        except SpaceError:
            logger.exception("Card resolver could not list live cards")
            return
        now = utc_now()
        due = [(space_id, card) for space_id, card in live_cards if _is_due(card, now)]
        if not due:
            return
        await asyncio.gather(*(self._resolve_guarded(space_id, card) for space_id, card in due))

    async def _resolve_guarded(self, space_id: str, card: SpaceCard) -> None:
        async with self._semaphore:
            try:
                await self.resolve_card(space_id, card)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive
                logger.exception("Unexpected error resolving card %s in space %s", card.id, space_id)

    async def resolve_card(self, space_id: str, card: SpaceCard) -> None:
        """Resolve one live card's binding and persist the outcome."""

        assert card.binding is not None  # callers pre-filter on binding
        binding = card.binding
        try:
            raw = await self._invoke_source(binding.source_tool, binding.source_params)
            content = _build_content(card.type, raw, binding.mapping)
        except BindingError as exc:
            await self._write_error(space_id, card.id, exc.code, str(exc))
            return
        except Exception as exc:  # tool invocation / timeout / unexpected shape
            await self._write_error(space_id, card.id, "binding_refresh_failed", str(exc))
            return
        await self._repository.apply_refresh(
            space_id,
            card.id,
            content=content,
            status=RefreshStatus.FRESH,
            last_error=None,
            last_refreshed_at=utc_now(),
        )

    async def _invoke_source(self, source_tool: str, params: dict[str, Any]) -> Any:
        if source_tool in self._hitl_tools:
            raise BindingError(
                "binding_forbidden_tool",
                f"Tool '{source_tool}' requires human approval and cannot back a live card.",
            )
        tool = self._tools_by_name.get(source_tool)
        if tool is None:
            raise BindingError("binding_unknown_tool", f"Tool '{source_tool}' is not available.")
        return await asyncio.wait_for(tool.ainvoke(params), timeout=self._invoke_timeout_s)

    async def _write_error(self, space_id: str, card_id: str, code: str, message: str) -> None:
        try:
            await self._repository.apply_refresh(
                space_id,
                card_id,
                content=None,  # keep last-good content
                status=RefreshStatus.ERROR,
                last_error=f"{code}: {message}"[:2000],
                last_refreshed_at=utc_now(),
            )
        except SpaceError:
            logger.exception("Card resolver could not persist error for card %s", card_id)


def _is_due(card: SpaceCard, now: Any) -> bool:
    binding = card.binding
    if binding is None or binding.refresh_mode != "interval" or binding.interval_ms is None:
        return False
    if card.last_refreshed_at is None:
        return True
    elapsed_ms = (now - card.last_refreshed_at).total_seconds() * 1000
    return elapsed_ms >= binding.interval_ms


def _build_content(card_type: CardType, raw: Any, mapping: dict[str, str] | None) -> CardContent:
    """Map a raw tool response into a validated CardContent for the card type."""

    if mapping is None:
        payload = raw if isinstance(raw, dict) else {}
    else:
        payload = {}
        for field, expression in mapping.items():
            try:
                payload[field] = jmespath.search(expression, raw)
            except JMESPathError as exc:
                raise BindingError("binding_invalid", f"Invalid JMESPath for '{field}': {exc}") from exc
    try:
        content = CardContent.model_validate(payload)
    except Exception as exc:
        raise BindingError("binding_invalid", f"Mapped content is not valid: {exc}") from exc
    required_field = REQUIRED_CONTENT_FIELD[card_type]
    if not getattr(content, required_field):
        raise BindingError(
            "binding_invalid",
            f"Card type '{card_type}' requires non-empty content.{required_field} after mapping.",
        )
    return content
