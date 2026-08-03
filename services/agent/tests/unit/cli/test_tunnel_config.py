import json

import pytest

from ops_pilot.tunnel.profile import resolve_tunnel_mcp_spec


def test_tunnel_config_resolves_stdio_server_command_and_env(tmp_path) -> None:
    config_path = tmp_path / ".mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "kibana": {
                        "command": "node",
                        "args": ["/tmp/mcp-server-kibana/dist/index.js"],
                        "env": {"KIBANA_URL": "https://kibana.example.com"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    spec = resolve_tunnel_mcp_spec(
        mcp_command=None,
        mcp_config=str(config_path),
        mcp_server="kibana",
    )

    assert spec.command == "node /tmp/mcp-server-kibana/dist/index.js"
    assert spec.env == {"KIBANA_URL": "https://kibana.example.com"}


def test_tunnel_config_requires_server_name_for_multiple_servers(tmp_path) -> None:
    config_path = tmp_path / ".mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "one": {"command": "node", "args": ["one.js"]},
                    "two": {"command": "node", "args": ["two.js"]},
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pass mcp_server"):
        resolve_tunnel_mcp_spec(
            mcp_command=None,
            mcp_config=str(config_path),
            mcp_server=None,
        )


def test_tunnel_config_rejects_mixed_command_and_config() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        resolve_tunnel_mcp_spec(
            mcp_command="node server.js",
            mcp_config="/tmp/.mcp.json",
            mcp_server="kibana",
        )
