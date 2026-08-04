import pytest

from ops_pilot.config.mcp_schema import MCPConfig, MCPConfigError
from ops_pilot.config.paths import REPO_ROOT


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


def test_mcp_config_parses_permission_lists():
    config = MCPConfig.from_mapping(
        {
            "mcpServers": {
                "dyna": {
                    "transport": "stdio",
                    "command": "npx",
                    "allow_tools": ["get_problems", "query_metrics"],
                    "hitl_tools": ["restart_service"],
                }
            }
        }
    )

    server = config.servers[0]
    assert server.allow_tools == ("get_problems", "query_metrics")
    assert server.hitl_tools == ("restart_service",)
    assert config.hitl_tool_names() == {"restart_service"}
    # Permission lists must not leak into the transport connection dict.
    assert "allow_tools" not in server.to_client_connection()
    assert "hitl_tools" not in server.to_client_connection()


def test_mcp_config_permission_lists_default_empty_when_omitted():
    config = MCPConfig.from_mapping({"mcpServers": {"dyna": {"transport": "stdio", "command": "npx"}}})

    assert config.servers[0].allow_tools == ()
    assert config.servers[0].hitl_tools == ()
    assert config.hitl_tool_names() == set()


def test_mcp_config_rejects_non_string_permission_entries():
    with pytest.raises(MCPConfigError, match="allow_tools"):
        MCPConfig.from_mapping(
            {"mcpServers": {"dyna": {"transport": "stdio", "command": "npx", "allow_tools": [1, 2]}}}
        )


def test_mcp_config_passes_cwd_to_stdio_connection():
    config = MCPConfig.from_mapping(
        {"mcpServers": {"dyna": {"transport": "stdio", "command": "npx", "cwd": "config"}}}
    )

    assert config.servers[0].to_client_connection()["cwd"] == str((REPO_ROOT / "config").resolve())
