from __future__ import annotations

from typing import Any, cast

import pytest

from ops_pilot.a2a.executor import create_executor
from ops_pilot.config.settings import load_settings


@pytest.mark.asyncio
async def test_a2a_executor_uses_client_safe_error_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    import a2a.server.tasks

    captured: dict[str, Any] = {}

    class FakeTaskUpdater:
        def __init__(self, **_: Any) -> None:
            pass

        async def submit(self) -> None:
            pass

        async def start_work(self, **_: Any) -> None:
            pass

        def new_agent_message(self, *, parts: list[Any]) -> list[Any]:
            return parts

        async def failed(self, *, message: list[Any]) -> None:
            captured["failed"] = message

    class FailingRuntime:
        async def ainvoke_text(self, *_: Any, **__: Any) -> str:
            raise RuntimeError("secret provider response")

        async def cancel_run(self, *_: Any, **__: Any) -> bool:
            return True

    class Context:
        task_id = "task-1"
        context_id = "context-1"

        def get_user_input(self) -> str:
            return "hello"

    monkeypatch.setattr(a2a.server.tasks, "TaskUpdater", FakeTaskUpdater)
    executor = create_executor(FailingRuntime(), load_settings(env={}, config={"app_env": "test"}))

    await executor.execute(cast(Any, Context()), cast(Any, object()))

    assert captured["failed"][0].text == "Unexpected server error."
