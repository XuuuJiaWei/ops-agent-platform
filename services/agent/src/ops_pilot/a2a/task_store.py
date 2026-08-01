"""In-memory A2A task store for local development."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    context_id: str | None
    status: str
    input_text: str
    output_text: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class InMemoryTaskStore:
    """Process-local task store; does not survive restarts."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._records: dict[str, TaskRecord] = {}

    def put(self, record: TaskRecord) -> TaskRecord:
        with self._lock:
            self._records[record.task_id] = record
        return record

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._records.get(task_id)

    def update(
        self,
        task_id: str,
        *,
        status: str,
        output_text: str | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        with self._lock:
            current = self._records[task_id]
            updated = TaskRecord(
                task_id=current.task_id,
                context_id=current.context_id,
                status=status,
                input_text=current.input_text,
                output_text=output_text if output_text is not None else current.output_text,
                error=error if error is not None else current.error,
                metadata=metadata if metadata is not None else current.metadata,
                created_at=current.created_at,
                updated_at=datetime.now(UTC).isoformat(),
            )
            self._records[task_id] = updated
            return updated

    def list(self) -> tuple[TaskRecord, ...]:
        with self._lock:
            return tuple(self._records.values())

