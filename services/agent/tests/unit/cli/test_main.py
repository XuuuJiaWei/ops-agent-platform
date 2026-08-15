from __future__ import annotations

import asyncio
from types import SimpleNamespace

from ops_pilot.cli import main as cli
from ops_pilot.config.settings import Settings


def test_configures_selector_event_loop_policy_on_windows(monkeypatch) -> None:
    policy = object()
    configured: list[object] = []

    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.asyncio, "WindowsSelectorEventLoopPolicy", lambda: policy)
    monkeypatch.setattr(cli.asyncio, "set_event_loop_policy", configured.append)

    cli._configure_event_loop_policy()

    assert configured == [policy]


def test_keeps_default_event_loop_policy_on_non_windows(monkeypatch) -> None:
    configured: list[asyncio.AbstractEventLoopPolicy] = []

    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.asyncio, "set_event_loop_policy", configured.append)

    cli._configure_event_loop_policy()

    assert configured == []


def test_serve_backend_lets_the_configured_event_loop_policy_select_the_loop(monkeypatch) -> None:
    captured_config: dict[str, object] = {}
    settings = Settings.model_validate({"chat_host": "127.0.0.1", "chat_port": 8123})

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli.asyncio, "run", lambda coroutine: coroutine.close() or object())
    monkeypatch.setattr(cli.uvicorn, "Config", lambda _app, **kwargs: captured_config.update(kwargs) or object())
    monkeypatch.setattr(cli.uvicorn, "Server", lambda _config: SimpleNamespace(run=lambda: None))

    assert cli._serve_backend(None, None) == 0
    assert captured_config["loop"] == "none"


def test_status_closes_the_runtime_it_builds(monkeypatch, capsys) -> None:
    runtime = SimpleNamespace(closed=False)

    async def close() -> None:
        runtime.closed = True

    async def build_runtime():
        runtime.aclose = close
        return runtime

    monkeypatch.setattr(cli, "build_agent_runtime", build_runtime)
    monkeypatch.setattr(cli, "build_runtime_status", lambda _: {"ok": True})

    assert asyncio.run(cli._print_status()) == 0
    assert runtime.closed is True
    assert '"ok": true' in capsys.readouterr().out
