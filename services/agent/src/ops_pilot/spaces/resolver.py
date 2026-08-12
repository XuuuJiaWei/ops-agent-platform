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
import json
import logging
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import ToolMessage

from ops_pilot.spaces.models import (
    RefreshStatus,
    SpaceCard,
    utc_now,
)
from ops_pilot.spaces.repository import SpaceError, SpaceRepository

logger = logging.getLogger("uvicorn.error")

# Upper bound on a stored raw snapshot's JSON size. Snapshots ride inside the
# space's ``cards`` JSONB column and are re-serialized on every refresh, so a
# runaway source (e.g. an unbounded Prometheus query) must not bloat the row.
MAX_RAW_SNAPSHOT_BYTES = 256 * 1024


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
        """Resolve one live card's binding and persist the raw snapshot.

        The resolver never shapes the data: it fetches from the read-only
        source tool and stores the raw response. The frontend replays the
        card's authored transform to produce displayed content.
        """

        assert card.binding is not None  # callers pre-filter on binding
        binding = card.binding
        try:
            raw = await self._invoke_source(binding.source_tool, binding.source_params)
            _guard_snapshot_size(raw)
        except BindingError as exc:
            await self._write_error(space_id, card.id, exc.code, str(exc))
            return
        except Exception as exc:  # tool invocation / timeout / unexpected shape
            await self._write_error(space_id, card.id, "binding_refresh_failed", str(exc))
            return
        await self._repository.apply_refresh(
            space_id,
            card.id,
            raw_snapshot=raw,
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
        # Invoke as a tool call (not a plain-dict invoke) so the langchain-mcp
        # adapter returns a ToolMessage carrying the MCP ``structuredContent``
        # artifact; a plain-dict invoke yields only the content and discards it.
        tool_call = {"type": "tool_call", "name": source_tool, "args": params, "id": "card-resolver"}
        result = await asyncio.wait_for(tool.ainvoke(tool_call), timeout=self._invoke_timeout_s)
        return _coerce_raw(result)

    async def _write_error(self, space_id: str, card_id: str, code: str, message: str) -> None:
        try:
            await self._repository.apply_refresh(
                space_id,
                card_id,
                raw_snapshot=None,  # keep last-good snapshot
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


def _coerce_raw(result: Any) -> Any:
    """Reduce a tool invocation result to a plain object for mapping.

    Layered to match MCP consumer norms (prefer structured, then text, then raw):

    1. ``ToolMessage`` with ``status='error'`` -> raise (the source failed).
    2. ``structuredContent`` artifact (machine-readable) -> use it verbatim.
    3. text content block(s) -> join, then JSON-decode when it looks like JSON.
    4. bare ``str`` -> JSON-decode when it looks like JSON, else keep the string.
    5. anything else (dict/list already) -> use as-is.
    """

    if isinstance(result, ToolMessage):
        if result.status == "error":
            raise BindingError(
                "binding_source_error",
                _content_text(result.content) or "Source tool reported an error.",
            )
        artifact = result.artifact
        if isinstance(artifact, dict) and artifact.get("structured_content") is not None:
            return artifact["structured_content"]
        result = result.content
    if isinstance(result, list) and result and all(isinstance(block, dict) and block.get("type") for block in result):
        text = _content_text(result)
        return _maybe_json(text) if text is not None else result
    if isinstance(result, str):
        return _maybe_json(result)
    return result


def _content_text(content: Any) -> str | None:
    """Join the text of any LangChain text content blocks (or return a bare str)."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        ]
        if parts:
            return "\n".join(parts)
    return None


def _maybe_json(text: str) -> Any:
    """Decode ``text`` as JSON only when it plausibly is JSON; else keep the string.

    Guards against turning free-form prose (or a bare number/quote) into a
    surprising type: only object/array-shaped payloads are decoded.
    """

    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return text
    try:
        return json.loads(stripped)
    except (ValueError, TypeError):
        return text


def _guard_snapshot_size(raw: Any) -> None:
    """Reject a snapshot whose JSON form would bloat the persisted space row."""

    try:
        size = len(json.dumps(raw, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return  # non-serializable payloads fail later; don't block here
    if size > MAX_RAW_SNAPSHOT_BYTES:
        raise BindingError(
            "binding_snapshot_too_large",
            f"Raw source snapshot is {size} bytes, over the {MAX_RAW_SNAPSHOT_BYTES}-byte limit; "
            "narrow the query or add a source-side limit.",
        )
