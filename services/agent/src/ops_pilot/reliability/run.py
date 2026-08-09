"""Run lifecycle and cooperative cancellation for protocol adapters."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    DEADLINE_EXCEEDED = "deadline_exceeded"


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    status: RunStatus
    cancellation_reason: str | None = None
    error: str | None = None


_current_run_id: ContextVar[str | None] = ContextVar("ops_pilot_run_id", default=None)


def current_run_id() -> str | None:
    """Return the protocol run ID visible to tool middleware."""

    return _current_run_id.get()


class RunController:
    """Track active run tasks and expose one cancellation interface."""

    def __init__(self, *, default_deadline_seconds: float | None = None) -> None:
        self._default_deadline_seconds = default_deadline_seconds
        self._snapshots: dict[str, RunSnapshot] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    async def run(
        self,
        run_id: str,
        operation: Callable[[], Awaitable[Any]],
        *,
        deadline_seconds: float | None = None,
    ) -> Any:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("RunController.run() requires an asyncio task.")
        async with self._lock:
            active = self._tasks.get(run_id)
            if active is not None and not active.done():
                raise RuntimeError(f"Run {run_id!r} is already active.")
            self._tasks[run_id] = task
            self._snapshots[run_id] = RunSnapshot(run_id=run_id, status=RunStatus.RUNNING)

        token: Token[str | None] = _current_run_id.set(run_id)
        timeout = self._default_deadline_seconds if deadline_seconds is None else deadline_seconds
        try:
            if timeout is None:
                result = await operation()
            else:
                async with asyncio.timeout(timeout):
                    result = await operation()
        except asyncio.CancelledError:
            self._set_status(run_id, RunStatus.CANCELLED)
            raise
        except TimeoutError:
            self._set_status(run_id, RunStatus.DEADLINE_EXCEEDED, error=f"deadline exceeded after {timeout:g}s")
            raise
        except BaseException as exc:
            self._set_status(run_id, RunStatus.FAILED, error=str(exc) or exc.__class__.__name__)
            raise
        else:
            self._set_status(run_id, RunStatus.COMPLETED)
            return result
        finally:
            _current_run_id.reset(token)
            async with self._lock:
                if self._tasks.get(run_id) is task:
                    self._tasks.pop(run_id, None)

    async def cancel(self, run_id: str, *, reason: str = "cancel requested") -> bool:
        async with self._lock:
            task = self._tasks.get(run_id)
            if task is None or task.done():
                return False
            snapshot = self._snapshots[run_id]
            self._snapshots[run_id] = replace(
                snapshot,
                status=RunStatus.CANCELLING,
                cancellation_reason=reason,
            )
            task.cancel(reason)
            return True

    async def iterate(
        self,
        run_id: str,
        source: AsyncIterator[Any],
        *,
        deadline_seconds: float | None = None,
    ) -> AsyncIterator[Any]:
        """Track an async event stream with the same run lifecycle semantics."""

        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("RunController.iterate() requires an asyncio task.")
        async with self._lock:
            active = self._tasks.get(run_id)
            if active is not None and not active.done():
                raise RuntimeError(f"Run {run_id!r} is already active.")
            self._tasks[run_id] = task
            self._snapshots[run_id] = RunSnapshot(run_id=run_id, status=RunStatus.RUNNING)

        token: Token[str | None] = _current_run_id.set(run_id)
        timeout = self._default_deadline_seconds if deadline_seconds is None else deadline_seconds
        try:
            if timeout is None:
                async for item in source:
                    yield item
            else:
                async with asyncio.timeout(timeout):
                    async for item in source:
                        yield item
        except asyncio.CancelledError:
            self._set_status(run_id, RunStatus.CANCELLED)
            raise
        except TimeoutError:
            self._set_status(run_id, RunStatus.DEADLINE_EXCEEDED, error=f"deadline exceeded after {timeout:g}s")
            raise
        except BaseException as exc:
            self._set_status(run_id, RunStatus.FAILED, error=str(exc) or exc.__class__.__name__)
            raise
        else:
            self._set_status(run_id, RunStatus.COMPLETED)
        finally:
            _current_run_id.reset(token)
            async with self._lock:
                if self._tasks.get(run_id) is task:
                    self._tasks.pop(run_id, None)

    def snapshot(self, run_id: str) -> RunSnapshot:
        try:
            return self._snapshots[run_id]
        except KeyError as exc:
            raise KeyError(f"Unknown run {run_id!r}.") from exc

    def _set_status(self, run_id: str, status: RunStatus, *, error: str | None = None) -> None:
        previous = self._snapshots[run_id]
        self._snapshots[run_id] = replace(previous, status=status, error=error)
