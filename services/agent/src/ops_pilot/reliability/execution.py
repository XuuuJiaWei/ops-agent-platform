"""Idempotent execution seam for side-effecting agent tool calls."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class ExecutionStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ToolCall:
    run_id: str
    tool_call_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    dependency: str
    retry_safe: bool

    @property
    def key(self) -> tuple[str, str]:
        return self.run_id, self.tool_call_id

    @property
    def arguments_hash(self) -> str:
        encoded = json.dumps(self.arguments, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class ExecutionRecord:
    call: ToolCall
    status: ExecutionStatus
    attempt: int = 0
    result: Any = None
    error: str | None = None


@dataclass(frozen=True)
class ToolExecutionOutcome:
    status: ExecutionStatus
    attempt: int
    value: Any = None
    reused: bool = False


class IdempotencyConflictError(RuntimeError):
    """The same tool call ID was reused for a different operation."""


class TransientToolError(RuntimeError):
    """A dependency failure that may succeed when retried."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        tool_result: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.tool_result = tool_result


class IndeterminateToolError(TransientToolError):
    """The transport failed after dispatch, so the side-effect outcome is unknown."""


class RecoverableToolError(RuntimeError):
    """A tool rejected the operation with feedback the Agent can act on."""

    def __init__(self, message: str, *, tool_result: Any) -> None:
        super().__init__(message)
        self.tool_result = tool_result


class CircuitOpenError(RuntimeError):
    """A dependency is failing persistently and is temporarily unavailable."""


@dataclass(frozen=True)
class CircuitBreakerPolicy:
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None
    probe_in_flight: bool = False


class DependencyCircuitBreaker:
    """Closed/open/half-open breaker isolated by dependency name."""

    def __init__(self, policy: CircuitBreakerPolicy) -> None:
        self._policy = policy
        self._states: dict[str, _CircuitState] = {}
        self._lock = asyncio.Lock()

    async def before_call(self, dependency: str) -> None:
        async with self._lock:
            state = self._states.setdefault(dependency, _CircuitState())
            if state.opened_at is None:
                return
            elapsed = time.monotonic() - state.opened_at
            if elapsed < self._policy.recovery_timeout_seconds or state.probe_in_flight:
                raise CircuitOpenError(f"Circuit for MCP server {dependency!r} is open.")
            state.probe_in_flight = True

    async def record_success(self, dependency: str) -> None:
        async with self._lock:
            self._states[dependency] = _CircuitState()

    async def record_failure(self, dependency: str) -> None:
        async with self._lock:
            state = self._states.setdefault(dependency, _CircuitState())
            state.failures += 1
            state.probe_in_flight = False
            if state.failures >= self._policy.failure_threshold:
                state.opened_at = time.monotonic()


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.25
    backoff_multiplier: float = 2.0
    jitter_ratio: float = 0.2

    def delay(self, completed_attempt: int) -> float:
        base = self.initial_backoff_seconds * self.backoff_multiplier ** (completed_attempt - 1)
        jitter = base * self.jitter_ratio
        return max(0.0, base + random.uniform(-jitter, jitter))


class MemoryExecutionJournal:
    """Process-local execution journal used by local development and tests."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ExecutionRecord] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def lock_for(self, key: tuple[str, str]) -> asyncio.Lock:
        async with self._guard:
            return self._locks.setdefault(key, asyncio.Lock())

    async def get(self, call: ToolCall) -> ExecutionRecord | None:
        record = self._records.get(call.key)
        if record is not None and (
            record.call.arguments_hash != call.arguments_hash
            or record.call.tool_name != call.tool_name
            or record.call.dependency != call.dependency
        ):
            raise IdempotencyConflictError(
                f"Tool call {call.tool_call_id!r} in run {call.run_id!r} was reused with different arguments."
            )
        return record

    async def put(self, record: ExecutionRecord) -> None:
        self._records[record.call.key] = record


class ExecutionJournal(Protocol):
    """Persistence interface required by the reliable execution Module."""

    async def lock_for(self, key: tuple[str, str]) -> AbstractAsyncContextManager[Any]: ...

    async def get(self, call: ToolCall) -> ExecutionRecord | None: ...

    async def put(self, record: ExecutionRecord) -> None: ...


class ReliableToolExecutor:
    """Execute a tool once per model-issued call ID and reuse terminal results."""

    def __init__(
        self,
        *,
        journal: ExecutionJournal,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker_policy: CircuitBreakerPolicy | None = None,
    ) -> None:
        self._journal = journal
        self._retry_policy = retry_policy or RetryPolicy()
        self._circuit_breaker = DependencyCircuitBreaker(circuit_breaker_policy or CircuitBreakerPolicy())

    async def execute(
        self,
        call: ToolCall,
        operation: Callable[[], Awaitable[Any]],
    ) -> ToolExecutionOutcome:
        lock = await self._journal.lock_for(call.key)
        async with lock:
            existing = await self._journal.get(call)
            if existing is not None and existing.status is ExecutionStatus.SUCCEEDED:
                return ToolExecutionOutcome(
                    status=existing.status,
                    attempt=existing.attempt,
                    value=existing.result,
                    reused=True,
                )
            if existing is not None and existing.status is ExecutionStatus.UNKNOWN:
                raise IndeterminateToolError(existing.error or "The previous tool outcome is unknown.")
            if existing is not None and existing.status is ExecutionStatus.CANCELLED:
                raise asyncio.CancelledError(existing.error or "The previous tool call was cancelled.")
            if existing is not None and existing.status is ExecutionStatus.FAILED:
                if existing.result is not None:
                    return ToolExecutionOutcome(
                        status=existing.status,
                        attempt=existing.attempt,
                        value=existing.result,
                        reused=True,
                    )
                raise RuntimeError(existing.error or "The previous tool call failed.")

            attempt = existing.attempt if existing is not None else 0
            if existing is not None and existing.status is ExecutionStatus.RUNNING and not call.retry_safe:
                error = "The previous worker stopped while this non-idempotent tool call was in flight."
                await self._journal.put(
                    ExecutionRecord(
                        call=call,
                        status=ExecutionStatus.UNKNOWN,
                        attempt=attempt,
                        error=error,
                    )
                )
                raise IndeterminateToolError(error)

            await self._circuit_breaker.before_call(call.dependency)
            try:
                while True:
                    attempt += 1
                    await self._journal.put(ExecutionRecord(call=call, status=ExecutionStatus.RUNNING, attempt=attempt))
                    try:
                        value = await operation()
                        break
                    except IndeterminateToolError as exc:
                        if call.retry_safe and attempt < self._retry_policy.max_attempts:
                            await asyncio.sleep(self._retry_policy.delay(attempt))
                            continue
                        status = ExecutionStatus.FAILED if call.retry_safe else ExecutionStatus.UNKNOWN
                        await self._journal.put(
                            ExecutionRecord(
                                call=call,
                                status=status,
                                attempt=attempt,
                                error=str(exc) or exc.__class__.__name__,
                            )
                        )
                        raise
                    except TransientToolError as exc:
                        if not call.retry_safe or attempt >= self._retry_policy.max_attempts:
                            await self._journal.put(
                                ExecutionRecord(
                                    call=call,
                                    status=ExecutionStatus.FAILED,
                                    attempt=attempt,
                                    result=exc.tool_result,
                                    error=str(exc) or exc.__class__.__name__,
                                )
                            )
                            raise
                        await asyncio.sleep(self._retry_policy.delay(attempt))
            except asyncio.CancelledError as exc:
                await self._journal.put(
                    ExecutionRecord(
                        call=call,
                        status=ExecutionStatus.CANCELLED,
                        attempt=attempt,
                        error=str(exc) or "cancelled",
                    )
                )
                raise
            except TransientToolError as exc:
                await self._circuit_breaker.record_failure(call.dependency)
                if exc.tool_result is not None:
                    return ToolExecutionOutcome(
                        status=ExecutionStatus.FAILED,
                        attempt=attempt,
                        value=exc.tool_result,
                    )
                raise
            except RecoverableToolError as exc:
                await self._circuit_breaker.record_success(call.dependency)
                await self._journal.put(
                    ExecutionRecord(
                        call=call,
                        status=ExecutionStatus.FAILED,
                        attempt=attempt,
                        result=exc.tool_result,
                        error=str(exc) or exc.__class__.__name__,
                    )
                )
                return ToolExecutionOutcome(
                    status=ExecutionStatus.FAILED,
                    attempt=attempt,
                    value=exc.tool_result,
                )
            except BaseException as exc:
                await self._journal.put(
                    ExecutionRecord(
                        call=call,
                        status=ExecutionStatus.FAILED,
                        attempt=attempt,
                        error=str(exc) or exc.__class__.__name__,
                    )
                )
                raise
            await self._circuit_breaker.record_success(call.dependency)
            record = ExecutionRecord(
                call=call,
                status=ExecutionStatus.SUCCEEDED,
                attempt=attempt,
                result=value,
            )
            await self._journal.put(record)
            return ToolExecutionOutcome(status=record.status, attempt=attempt, value=value)
