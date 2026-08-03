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


class DummyAGUIAgent:
    def __init__(self, **_: object) -> None:
        pass


class FakeReloadResult:
    def as_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "generation": 1,
            "dynamic_mcp": {"tool_count": 0, "servers": []},
        }


class FakeRuntimeManager:
    def __init__(self) -> None:
        self.applied_server = None

    def status(self) -> FakeReloadResult:
        return FakeReloadResult()

    async def apply_mcp_server(self, server) -> FakeReloadResult:
        self.applied_server = server
        return FakeReloadResult()

    async def remove_mcp_server(self, name: str) -> FakeReloadResult:
        return FakeReloadResult()


class FakeLocalBridgeManager:
    def __init__(self) -> None:
        self.started_config = None
        self.waited_tunnel_id = None
        self.stopped_tunnel_id = None

    def status(self) -> dict:
        return {}

    async def start(self, config) -> object:
        self.started_config = config
        return object()

    async def wait_connected(self, tunnel_id: str, *, timeout: float) -> None:
        self.waited_tunnel_id = tunnel_id

    async def stop(self, tunnel_id: str) -> None:
        self.stopped_tunnel_id = tunnel_id

    async def shutdown(self) -> None:
        # Invoked by the FastAPI lifespan shutdown when this fake is installed.
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
async def test_unified_backend_mounts_chat_a2a_and_tunnel_routes(monkeypatch) -> None:
    _patch_agui(monkeypatch)

    settings = load_settings({"APP_ENV": "test", "ASSISTANT_ID": "agent"})
    app = await create_backend_app(settings, runtime=DummyRuntime())
    paths = {path for route in app.routes if (path := getattr(route, "path", None))}

    assert "/chat" in paths
    assert "/a2a/jsonrpc" in paths
    assert "/a2a/.well-known/agent-card.json" in paths

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/dev/mcp-tunnels").status_code == 200


@pytest.mark.asyncio
async def test_tunnel_agent_config_applies_to_runtime_manager(monkeypatch) -> None:
    import ops_pilot.tunnel.app as tunnel_app

    _patch_agui(monkeypatch)
    monkeypatch.setattr(tunnel_app.manager, "get", lambda tunnel_id: object())

    settings = load_settings({"APP_ENV": "test", "ASSISTANT_ID": "agent"})
    app = await create_backend_app(settings, runtime=DummyRuntime())
    fake_manager = FakeRuntimeManager()
    app.state.agent_runtime_manager = fake_manager

    with TestClient(app) as client:
        response = client.put(
            "/dev/mcp-tunnels/local-dev/agent-config",
            json={"token": "secret"},
        )

    assert response.status_code == 200
    assert fake_manager.applied_server.name == "local-dev"
    assert fake_manager.applied_server.transport == "streamable_http"
    assert fake_manager.applied_server.url == "http://testserver/dev/mcp-tunnels/local-dev/mcp"
    assert fake_manager.applied_server.headers == {"Authorization": "Bearer secret"}


@pytest.mark.asyncio
async def test_tunnel_agent_config_starts_local_bridge_for_profile(monkeypatch) -> None:
    _patch_agui(monkeypatch)

    settings = load_settings({"APP_ENV": "test", "ASSISTANT_ID": "agent"})
    app = await create_backend_app(settings, runtime=DummyRuntime())
    fake_runtime_manager = FakeRuntimeManager()
    fake_bridge_manager = FakeLocalBridgeManager()
    app.state.agent_runtime_manager = fake_runtime_manager
    app.state.local_bridge_manager = fake_bridge_manager

    with TestClient(app) as client:
        response = client.put(
            "/dev/mcp-tunnels/kibana/agent-config",
            json={
                "mcp_config": "/Users/me/.mcp.json",
                "mcp_server": "kibana",
                "server_url": "http://127.0.0.1:8123",
            },
        )

    assert response.status_code == 200
    assert fake_bridge_manager.started_config.tunnel_id == "kibana"
    assert fake_bridge_manager.started_config.mcp_config == "/Users/me/.mcp.json"
    assert fake_bridge_manager.started_config.mcp_server == "kibana"
    assert fake_bridge_manager.waited_tunnel_id == "kibana"
    assert fake_runtime_manager.applied_server.name == "kibana"


@pytest.mark.asyncio
async def test_tunnel_agent_config_requires_connected_tunnel(monkeypatch) -> None:
    _patch_agui(monkeypatch)

    settings = load_settings({"APP_ENV": "test", "ASSISTANT_ID": "agent"})
    app = await create_backend_app(settings, runtime=DummyRuntime())
    app.state.agent_runtime_manager = FakeRuntimeManager()

    with TestClient(app) as client:
        response = client.put("/dev/mcp-tunnels/not-connected/agent-config", json={})

    assert response.status_code == 503
    assert "not-connected" in response.json()["detail"]
    assert "Configure a local MCP profile" in response.json()["detail"]
