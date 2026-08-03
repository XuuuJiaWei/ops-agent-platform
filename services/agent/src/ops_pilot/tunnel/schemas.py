"""Message shapes for the local MCP tunnel relay."""

from __future__ import annotations

from typing import Any

JSONValue = dict[str, Any] | list[Any] | str | int | float | bool | None
JSONRPCMessage = dict[str, Any]

MCP_SESSION_ID_HEADER = "mcp-session-id"
MCP_PROTOCOL_VERSION_HEADER = "mcp-protocol-version"

TUNNEL_AUTH_ENV = "OPS_PILOT_TUNNEL_TOKEN"


def is_jsonrpc_request(message: JSONRPCMessage) -> bool:
    return "id" in message and isinstance(message.get("method"), str)


def is_initialize_request(message: JSONRPCMessage) -> bool:
    return is_jsonrpc_request(message) and message.get("method") == "initialize"


def is_jsonrpc_notification(message: JSONRPCMessage) -> bool:
    return "id" not in message and isinstance(message.get("method"), str)


def make_jsonrpc_error(
    *,
    request_id: Any,
    code: int,
    message: str,
) -> JSONRPCMessage:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
