from ops_pilot.a2a.task_store import InMemoryTaskStore, TaskRecord


def test_in_memory_task_store_put_get_update():
    store = InMemoryTaskStore()
    record = store.put(
        TaskRecord(task_id="task-1", context_id="ctx-1", status="working", input_text="hi")
    )

    assert store.get("task-1") == record

    updated = store.update("task-1", status="completed", output_text="ok")

    assert updated.status == "completed"
    assert updated.output_text == "ok"
    assert len(store.list()) == 1

