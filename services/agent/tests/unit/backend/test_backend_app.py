import pytest
from fastapi.testclient import TestClient

from ops_pilot.backend import create_backend_app
from ops_pilot.config.settings import load_settings


class DummyRuntime:
    graph = object()

    def runnable_config(self, **_: object) -> dict:
        return {}

    async def ainvoke_text(self, text: str, **_: object) -> str:
        return f"ok: {text}"


class CloseTrackingRuntime(DummyRuntime):
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class DummyAGUIAgent:
    def __init__(self, **_: object) -> None:
        pass


def _patch_agui(monkeypatch) -> None:
    """Replace the heavy AG-UI / CopilotKit wiring with fakes.

    Must run before create_backend_app so the mounted /chat endpoint is a stub.
    """

    import ag_ui_langgraph
    import copilotkit
    import copilotkit.langgraph

    def add_fake_langgraph_endpoint(*, app, path: str, **_: object) -> None:
        @app.post(path)
        async def fake_chat() -> dict[str, str]:
            return {"ok": "chat"}

    monkeypatch.setattr(
        ag_ui_langgraph,
        "add_langgraph_fastapi_endpoint",
        add_fake_langgraph_endpoint,
    )
    monkeypatch.setattr(copilotkit, "LangGraphAGUIAgent", DummyAGUIAgent)
    monkeypatch.setattr(copilotkit.langgraph, "copilotkit_customize_config", lambda **_: {})


@pytest.mark.asyncio
async def test_unified_backend_mounts_chat_a2a_and_health_routes(monkeypatch) -> None:
    _patch_agui(monkeypatch)

    settings = load_settings(env={}, config={"app_env": "test", "assistant_id": "agent"})
    app = await create_backend_app(settings, runtime=DummyRuntime())

    with TestClient(app) as client:
        paths = {path for route in app.routes if (path := getattr(route, "path", None))}
        assert "/chat" in paths
        assert "/a2a/jsonrpc" in paths
        assert "/a2a/.well-known/agent-card.json" in paths
        assert client.get("/health").status_code == 200


@pytest.mark.asyncio
async def test_backend_builds_runtime_inside_lifespan(monkeypatch) -> None:
    import ops_pilot.backend as backend

    _patch_agui(monkeypatch)

    created: list[CloseTrackingRuntime] = []

    async def fake_create_agent_runtime_async(_settings):
        runtime = CloseTrackingRuntime()
        created.append(runtime)
        return runtime

    monkeypatch.setattr(backend, "create_agent_runtime_async", fake_create_agent_runtime_async)
    settings = load_settings(env={}, config={"app_env": "test", "assistant_id": "agent"})

    app = await create_backend_app(settings)

    assert created == []

    with TestClient(app) as client:
        assert len(created) == 1
        assert created[0].closed is False
        assert client.get("/health").status_code == 200

    assert created[0].closed is True
