import asyncio
from contextlib import AsyncExitStack, asynccontextmanager

import pytest

from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.mcp import loader
from ops_pilot.mcp.loader import PersistentMCPSessions, RequiredMCPServerError, _safe_error, load_mcp_tools


def test_safe_error_unwraps_exception_groups() -> None:
    error = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [RuntimeError("Tunnel 'local-dev' is not connected.")],
    )

    assert _safe_error(error) == "Tunnel 'local-dev' is not connected."


@pytest.mark.asyncio
async def test_persistent_sessions_ignore_stdio_sigterm_shutdown_noise() -> None:
    stack = AsyncExitStack()

    @asynccontextmanager
    async def noisy_shutdown():
        try:
            yield
        finally:
            raise ExceptionGroup(
                "unhandled errors in a TaskGroup",
                [ValueError("Received SIGTERM, terminating child process...")],
            )

    await stack.enter_async_context(noisy_shutdown())
    sessions = PersistentMCPSessions(stack)

    await sessions.aclose()


@pytest.mark.asyncio
async def test_required_server_reports_missing_env_reference(monkeypatch) -> None:
    monkeypatch.delenv("DT_MISSING_TOKEN", raising=False)
    config = MCPConfig.from_mapping(
        {
            "mcpServers": {
                "dyna": {
                    "required": True,
                    "transport": "stdio",
                    "command": "npx",
                    "env": {"DT_MISSING_TOKEN": "${DT_MISSING_TOKEN}"},
                }
            }
        }
    )

    with pytest.raises(RequiredMCPServerError, match="DT_MISSING_TOKEN"):
        await load_mcp_tools(config)


@pytest.mark.asyncio
async def test_optional_server_records_missing_env_reference(monkeypatch) -> None:
    monkeypatch.delenv("DT_MISSING_TOKEN", raising=False)
    config = MCPConfig.from_mapping(
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

    result = await load_mcp_tools(config)

    assert result.tools == []
    assert result.status.servers[0].ok is False
    assert "DT_MISSING_TOKEN" in result.status.servers[0].error


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
