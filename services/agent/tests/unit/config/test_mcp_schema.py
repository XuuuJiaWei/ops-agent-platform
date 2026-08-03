import pytest

from ops_pilot.config.mcp_schema import MCPConfig, MCPConfigError


def test_mcp_config_accepts_stdio_and_http_servers():
    config = MCPConfig.from_mapping(
        {
            "mcpServers": {
                "local": {
                    "transport": "stdio",
                    "command": "python",
                    "args": ["server.py"],
                    "required": True,
                },
                "remote": {
                    "transport": "http",
                    "url": "http://localhost:8000/mcp",
                    "headers": {"X-Test": "1"},
                },
            }
        }
    )

    assert [server.name for server in config.servers] == ["local", "remote"]
    assert config.servers[0].required is True
    assert config.servers[1].to_client_connection()["url"] == "http://localhost:8000/mcp"


def test_mcp_config_rejects_missing_required_connection_fields():
    with pytest.raises(MCPConfigError):
        MCPConfig.from_mapping({"mcpServers": {"broken": {"transport": "http"}}})
