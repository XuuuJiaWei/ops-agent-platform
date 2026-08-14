"""Persistence factory selection tests.

The memory paths are covered without any external services. The Postgres paths
run only when ``TEST_DATABASE_URL`` points at a reachable database (see
``deploy/postgres``), so the default suite stays hermetic.
"""

from __future__ import annotations

import os

import pytest

from ops_pilot.a2a.task_store import create_task_store
from ops_pilot.agent.runtime import _create_checkpointer
from ops_pilot.config.settings import load_settings

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
requires_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="Set TEST_DATABASE_URL to run persistence integration tests (see deploy/postgres).",
)


@pytest.mark.asyncio
async def test_create_checkpointer_defaults_to_in_memory_saver():
    settings = load_settings(env={}, config={"app_env": "test"})

    checkpointer, closer = await _create_checkpointer(settings)

    assert checkpointer is not None
    assert type(checkpointer).__name__ in {"MemorySaver", "InMemorySaver"}
    assert closer is None


@pytest.mark.asyncio
async def test_create_task_store_defaults_to_in_memory_store():
    settings = load_settings(env={}, config={"app_env": "test"})

    store, closer = await create_task_store(settings)

    assert type(store).__name__ == "InMemoryTaskStore"
    assert closer is None


@requires_db
@pytest.mark.asyncio
async def test_postgres_checkpointer_persists_and_resumes_across_reopen():
    """A checkpoint written by one saver is readable by a fresh saver + pool.

    This is the durable-execution guarantee: after a restart, a new process
    reconstructs thread state from Postgres using the same thread_id.
    """

    from langgraph.checkpoint.base import empty_checkpoint

    settings = load_settings(
        env={"DATABASE_URL": TEST_DATABASE_URL},
        config={"persistence": {"backend": "postgres"}},
    )
    thread_id = "test-resume-thread"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    checkpointer, closer = await _create_checkpointer(settings)
    assert checkpointer is not None
    assert closer is not None
    try:
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"marker": "written-before-restart"}
        await checkpointer.aput(config, checkpoint, {"source": "test"}, {})
    finally:
        await closer()

    # Simulate a restart: brand-new saver + connection pool, same database.
    reopened, reopened_closer = await _create_checkpointer(settings)
    assert reopened is not None
    assert reopened_closer is not None
    try:
        tuple_ = await reopened.aget_tuple(config)
        assert tuple_ is not None
        assert tuple_.checkpoint["channel_values"]["marker"] == "written-before-restart"
    finally:
        await reopened_closer()


@requires_db
@pytest.mark.asyncio
async def test_postgres_task_store_persists_and_resumes_across_reopen():
    from a2a.server.context import ServerCallContext
    from a2a.types import Task, TaskState, TaskStatus

    settings = load_settings(
        env={"DATABASE_URL": TEST_DATABASE_URL},
        config={"persistence": {"backend": "postgres"}},
    )
    context = ServerCallContext()
    task = Task(
        id="test-task-1",
        context_id="test-context-1",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
    )

    store, closer = await create_task_store(settings)
    assert closer is not None
    try:
        await store.save(task, context)
    finally:
        await closer()

    reopened, reopened_closer = await create_task_store(settings)
    assert reopened_closer is not None
    try:
        loaded = await reopened.get("test-task-1", context)
        assert loaded is not None
        assert loaded.id == "test-task-1"
    finally:
        await reopened_closer()
