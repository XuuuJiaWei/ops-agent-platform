import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest

from ops_pilot.config.interpolation import MissingEnvironmentError
from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.mcp import loader
from ops_pilot.mcp.loader import RequiredMCPServerError, load_mcp_tools


class _FakeClient:
    results: dict[str, Any] = {}
    last_connections: dict[str, Any] = {}

    def __init__(self, connections, **kwargs):
        self.connections = connections
        type(self).last_connections = connections
        self.kwargs = kwargs

    async def get_tools(self, *, server_name):
        result = self.results[server_name]
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            return await cast(Callable[[], Awaitable[Any]], result)()
        return result


def _install_client(monkeypatch, results: dict[str, Any]) -> None:
    _FakeClient.results = results
    monkeypatch.setattr(loader, "MultiServerMCPClient", _FakeClient)


def test_missing_env_reference_fails_fast_at_config_build(monkeypatch) -> None:
    monkeypatch.delenv("DT_MISSING_TOKEN", raising=False)

    with pytest.raises(MissingEnvironmentError, match="DT_MISSING_TOKEN"):
        MCPConfig.from_mapping(
            {
                "mcpServers": {
                    "dyna": {
                        "transport": "stdio",
                        "command": "npx",
                        "env": {"DT_MISSING_TOKEN": "${DT_MISSING_TOKEN}"},
                    }
                }
            }
        )


def test_url_interpolates_from_injected_env() -> None:
    config = MCPConfig.from_mapping(
        {
            "mcpServers": {
                "prometheus": {
                    "transport": "streamable_http",
                    "url": "https://prometheus-otel.${OTEL_SHOOT_DOMAIN}/mcp",
                }
            }
        },
        env={"OTEL_SHOOT_DOMAIN": "abc.shoot.test"},
    )

    assert config.servers[0].url == "https://prometheus-otel.abc.shoot.test/mcp"


def test_missing_url_var_fails_fast() -> None:
    with pytest.raises(MissingEnvironmentError, match="OTEL_SHOOT_DOMAIN"):
        MCPConfig.from_mapping(
            {
                "mcpServers": {
                    "prometheus": {
                        "transport": "streamable_http",
                        "url": "https://prometheus-otel.${OTEL_SHOOT_DOMAIN}/mcp",
                    }
                }
            },
            env={},
        )


@pytest.mark.asyncio
async def test_optional_server_failure_does_not_block_other_servers(monkeypatch) -> None:
    _install_client(monkeypatch, {"broken": ConnectionError("TLS EOF"), "healthy": []})
    config = MCPConfig.from_mapping(
        {
            "mcpServers": {
                "broken": {"transport": "stdio", "command": "broken"},
                "healthy": {"transport": "stdio", "command": "healthy"},
            }
        }
    )

    result = await load_mcp_tools(config)

    assert [status.ok for status in result.status.servers] == [False, True]
    assert result.status.servers[0].error == "TLS EOF"


@pytest.mark.asyncio
async def test_required_server_failure_fails_startup(monkeypatch) -> None:
    _install_client(monkeypatch, {"required": ConnectionError("TLS EOF")})
    config = MCPConfig.from_mapping(
        {
            "mcpServers": {
                "required": {
                    "required": True,
                    "transport": "stdio",
                    "command": "required",
                }
            }
        }
    )

    with pytest.raises(RequiredMCPServerError, match="required.*TLS EOF"):
        await load_mcp_tools(config)


@pytest.mark.asyncio
async def test_required_server_recovers_from_transient_connection_failure(monkeypatch) -> None:
    attempts = 0

    async def flaky_load() -> list[Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("TLS EOF")
        return []

    _install_client(monkeypatch, {"required": flaky_load})
    config = MCPConfig.from_mapping(
        {
            "mcpServers": {
                "required": {
                    "required": True,
                    "transport": "stdio",
                    "command": "required",
                }
            }
        }
    )

    result = await load_mcp_tools(config)

    assert result.status.servers[0].ok is True
    assert attempts == 2


@pytest.mark.asyncio
async def test_streamable_http_uses_transport_connect_retries(monkeypatch) -> None:
    _install_client(monkeypatch, {"remote": []})
    config = MCPConfig.from_mapping(
        {
            "mcpServers": {
                "remote": {
                    "transport": "streamable_http",
                    "url": "https://example.test/mcp",
                }
            }
        }
    )

    await load_mcp_tools(config)

    factory = _FakeClient.last_connections["remote"]["httpx_client_factory"]
    client = factory(headers={"X-Test": "yes"}, timeout=None, auth=None)
    try:
        assert client.follow_redirects is True
        assert client.headers["X-Test"] == "yes"
        assert client._transport._pool._retries == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_servers_are_loaded_concurrently(monkeypatch) -> None:
    both_started = asyncio.Event()
    started: set[str] = set()

    def coordinated(name: str):
        async def load():
            started.add(name)
            if started == {"one", "two"}:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=0.2)
            return []

        return load

    _install_client(monkeypatch, {"one": coordinated("one"), "two": coordinated("two")})
    config = MCPConfig.from_mapping(
        {
            "mcpServers": {
                "one": {"transport": "stdio", "command": "one"},
                "two": {"transport": "stdio", "command": "two"},
            }
        }
    )

    result = await asyncio.wait_for(load_mcp_tools(config), timeout=0.5)

    assert [status.name for status in result.status.servers] == ["one", "two"]
    assert all(status.ok for status in result.status.servers)
