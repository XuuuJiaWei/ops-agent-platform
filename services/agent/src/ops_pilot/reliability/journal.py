"""Durable adapters for the reliable tool execution journal."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar, Token
from typing import Any

from ops_pilot.config.settings import Settings
from ops_pilot.reliability.execution import ExecutionRecord, ExecutionStatus, IdempotencyConflictError, ToolCall
from ops_pilot.reliability.serde import ExecutionValueCodec

_locked_connection: ContextVar[Any | None] = ContextVar("ops_pilot_journal_connection", default=None)


class _PostgresAdvisoryLock:
    """Hold a transaction-independent lock on one pooled connection."""

    def __init__(self, pool: Any, key: int) -> None:
        self._pool = pool
        self._key = key
        self._connection_context: AbstractAsyncContextManager[Any] | None = None
        self._connection: Any | None = None
        self._connection_token: Token[Any | None] | None = None

    async def __aenter__(self) -> _PostgresAdvisoryLock:
        connection_context = self._pool.connection()
        connection = await connection_context.__aenter__()
        self._connection_context = connection_context
        self._connection = connection
        await connection.execute("SELECT pg_advisory_lock(%s)", (self._key,))
        self._connection_token = _locked_connection.set(connection)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            if self._connection is not None:
                await self._connection.execute("SELECT pg_advisory_unlock(%s)", (self._key,))
        finally:
            if self._connection_token is not None:
                _locked_connection.reset(self._connection_token)
            if self._connection_context is not None:
                await self._connection_context.__aexit__(exc_type, exc, traceback)


class PostgresExecutionJournal:
    """Persistent journal with a cross-process advisory lock per tool call."""

    def __init__(self, pool: Any, *, codec: ExecutionValueCodec | None = None) -> None:
        self._pool = pool
        self._codec = codec or ExecutionValueCodec()

    async def setup(self) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ops_pilot_tool_executions (
                    run_id TEXT NOT NULL,
                    tool_call_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_hash TEXT NOT NULL,
                    dependency TEXT NOT NULL,
                    retry_safe BOOLEAN NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    result_type TEXT,
                    result_payload BYTEA,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (run_id, tool_call_id)
                )
                """
            )

    @asynccontextmanager
    async def _connection(self):
        locked = _locked_connection.get()
        if locked is not None:
            yield locked
            return
        async with self._pool.connection() as connection:
            yield connection

    async def lock_for(self, key: tuple[str, str]) -> _PostgresAdvisoryLock:
        encoded = "\0".join(key).encode()
        lock_key = int.from_bytes(hashlib.blake2b(encoded, digest_size=8).digest(), signed=True)
        return _PostgresAdvisoryLock(self._pool, lock_key)

    async def get(self, call: ToolCall) -> ExecutionRecord | None:
        from psycopg.rows import dict_row

        async with self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT tool_name, arguments_hash, dependency, retry_safe, status,
                           attempt, result_type, result_payload, error
                      FROM ops_pilot_tool_executions
                     WHERE run_id = %s AND tool_call_id = %s
                    """,
                    call.key,
                )
                row = await cursor.fetchone()
        if row is None:
            return None
        if (
            row["tool_name"] != call.tool_name
            or row["arguments_hash"] != call.arguments_hash
            or row["dependency"] != call.dependency
        ):
            raise IdempotencyConflictError(
                f"Tool call {call.tool_call_id!r} in run {call.run_id!r} was reused with different arguments."
            )
        result = None
        if row["result_type"] is not None and row["result_payload"] is not None:
            result = self._codec.loads_typed((row["result_type"], bytes(row["result_payload"])))
        return ExecutionRecord(
            call=call,
            status=ExecutionStatus(row["status"]),
            attempt=row["attempt"],
            result=result,
            error=row["error"],
        )

    async def put(self, record: ExecutionRecord) -> None:
        result_type: str | None = None
        result_payload: bytes | None = None
        if record.result is not None:
            result_type, result_payload = self._codec.dumps_typed(record.result)
        async with self._connection() as connection:
            await connection.execute(
                """
                INSERT INTO ops_pilot_tool_executions (
                    run_id, tool_call_id, tool_name, arguments_hash, dependency,
                    retry_safe, status, attempt, result_type, result_payload, error
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, tool_call_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    attempt = EXCLUDED.attempt,
                    result_type = EXCLUDED.result_type,
                    result_payload = EXCLUDED.result_payload,
                    error = EXCLUDED.error,
                    updated_at = NOW()
                """,
                (
                    record.call.run_id,
                    record.call.tool_call_id,
                    record.call.tool_name,
                    record.call.arguments_hash,
                    record.call.dependency,
                    record.call.retry_safe,
                    record.status.value,
                    record.attempt,
                    result_type,
                    result_payload,
                    record.error,
                ),
            )


async def create_execution_journal(
    settings: Settings,
) -> tuple[Any, Callable[[], Awaitable[None]] | None]:
    """Create a process-local or Postgres execution journal with its closer."""

    if settings.persistence_backend != "postgres":
        from ops_pilot.reliability.execution import MemoryExecutionJournal

        return MemoryExecutionJournal(), None

    from psycopg_pool import AsyncConnectionPool

    conn_string = settings.psycopg_database_url()
    if not conn_string:
        raise RuntimeError("persistence.backend is 'postgres' but DATABASE_URL is not set.")
    pool = AsyncConnectionPool(
        conninfo=conn_string,
        max_size=10,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open(wait=True)
    journal = PostgresExecutionJournal(pool)
    try:
        if settings.persistence_setup_on_start:
            await journal.setup()
    except Exception:
        await pool.close()
        raise

    async def close() -> None:
        await pool.close()

    return journal, close
