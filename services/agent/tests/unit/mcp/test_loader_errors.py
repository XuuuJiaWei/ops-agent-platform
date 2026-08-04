import pytest

from ops_pilot.config.mcp_schema import MCPConfig
from ops_pilot.mcp.loader import RequiredMCPServerError, _safe_error, load_mcp_tools


def test_safe_error_unwraps_exception_groups() -> None:
    error = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [RuntimeError("Tunnel 'local-dev' is not connected.")],
    )

    assert _safe_error(error) == "Tunnel 'local-dev' is not connected."


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
