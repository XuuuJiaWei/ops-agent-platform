from __future__ import annotations

from typing import Any, cast

import pytest

from ops_pilot.mcp.spec import MCPDeclarationError, MCPServerCatalog, MCPServerSpec


def test_mcp_catalog_is_declared_by_the_host_not_loaded_from_a_global_file() -> None:
    server = MCPServerSpec(
        name="metrics",
        transport="streamable_http",
        url="https://metrics.example/mcp",
        allow_tools=("query",),
    )

    assert MCPServerCatalog((server,)).servers == (server,)

    connection = cast(dict[str, Any], server.to_client_connection())
    assert connection["url"] == "https://metrics.example/mcp"


def test_mcp_catalog_rejects_duplicate_host_declarations() -> None:
    server = MCPServerSpec(name="metrics", transport="stdio", command="node")

    with pytest.raises(MCPDeclarationError, match="unique"):
        MCPServerCatalog((server, server))
