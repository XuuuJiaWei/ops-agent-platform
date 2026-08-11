import asyncio

import pytest

from ops_pilot.config.interpolation import MissingEnvironmentError
from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.mcp import loader
from ops_pilot.mcp.loader import RequiredMCPServerError, _safe_error, load_mcp_tools


def test_safe_error_unwraps_exception_groups() -> None:
    error = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [RuntimeError("MCP server 'kubernetes' is not connected.")],
    )

    assert _safe_error(error) == "MCP server 'kubernetes' is not connected."


def test_missing_env_reference_fails_fast_at_config_build(monkeypatch) -> None:
    # New architecture: interpolation happens once at config construction and a
    # missing var fails fast for ANY server (required or optional), rather than
    # degrading per-server at load time.
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
async def test_optional_server_timeout_does_not_block_other_servers(monkeypatch) -> None:
    async def slow_load(_server):
        await asyncio.sleep(10)

    monkeypatch.setattr(loader, "_load_single_server", slow_load)
    config = MCPConfig.from_mapping(
        {
            "mcpServers": {
                "slow": {
                    "transport": "stdio",
                    "command": "npx",
                    "timeout": 0.01,
                }
            }
        }
    )

    result = await load_mcp_tools(config)

    assert result.tools == []
    assert result.status.servers[0].ok is False
    assert "timed out after 0.01s" in result.status.servers[0].error


@pytest.mark.asyncio
async def test_required_server_timeout_fails_startup(monkeypatch) -> None:
    async def slow_load(_server):
        await asyncio.sleep(10)

    monkeypatch.setattr(loader, "_load_single_server", slow_load)
    config = MCPConfig.from_mapping(
        {
            "mcpServers": {
                "slow": {
                    "required": True,
                    "transport": "stdio",
                    "command": "npx",
                    "timeout": 0.01,
                }
            }
        }
    )

    with pytest.raises(RequiredMCPServerError, match="timed out after 0.01s"):
        await load_mcp_tools(config)


@pytest.mark.asyncio
async def test_servers_are_started_concurrently(monkeypatch) -> None:
    both_started = asyncio.Event()
    started: set[str] = set()

    async def coordinated_load(server):
        started.add(server.name)
        if started == {"one", "two"}:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.2)
        return []

    monkeypatch.setattr(loader, "_load_single_server", coordinated_load)
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
