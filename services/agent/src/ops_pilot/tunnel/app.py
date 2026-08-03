"""FastAPI routes for the protocol-level MCP tunnel relay."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Request, Response, WebSocket, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from ops_pilot.agent.manager import AgentRuntimeManager
from ops_pilot.config.mcp_schema import MCPConfigError, MCPServerConfig
from ops_pilot.tunnel.local_bridge import LocalBridgeConfig, LocalBridgeManager
from ops_pilot.tunnel.manager import (
    TunnelNotConnectedError,
    TunnelRequestError,
    manager,
    new_session_id,
)
from ops_pilot.tunnel.schemas import (
    MCP_SESSION_ID_HEADER,
    TUNNEL_AUTH_ENV,
    JSONRPCMessage,
    is_initialize_request,
    is_jsonrpc_notification,
    is_jsonrpc_request,
    make_jsonrpc_error,
)

router = APIRouter(prefix="/dev/mcp-tunnels", tags=["mcp-tunnels"])


class TunnelAgentConfigRequest(BaseModel):
    token: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: float | None = None
    server_url: str | None = None
    mcp_command: str | None = None
    mcp_config: str | None = None
    mcp_server: str | None = None
    cwd: str | None = None
    connect_timeout: float = 10.0


@router.get("")
async def list_tunnels() -> dict[str, Any]:
    return {"tunnels": manager.status()}


@router.get("/agent-config")
async def get_agent_config(request: Request) -> dict[str, Any]:
    return _runtime_manager(request).status().as_dict()


@router.get("/local-bridges")
async def get_local_bridges(request: Request) -> dict[str, Any]:
    return {"bridges": _local_bridge_manager(request).status()}


@router.put("/{tunnel_id}/agent-config")
async def apply_tunnel_agent_config(
    request: Request,
    tunnel_id: str,
    body: TunnelAgentConfigRequest | None = None,
) -> dict[str, Any]:
    payload = body or TunnelAgentConfigRequest()
    headers = dict(payload.headers)
    token = (payload.token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        if _has_local_bridge_profile(payload):
            await _local_bridge_manager(request).start(
                LocalBridgeConfig(
                    tunnel_id=tunnel_id,
                    server_url=payload.server_url or _default_backend_url(request),
                    token=token or None,
                    mcp_command=_optional_non_empty(payload.mcp_command),
                    mcp_config=_optional_non_empty(payload.mcp_config),
                    mcp_server=_optional_non_empty(payload.mcp_server),
                    cwd=_optional_non_empty(payload.cwd),
                )
            )
            await _local_bridge_manager(request).wait_connected(
                tunnel_id,
                timeout=payload.connect_timeout,
            )
        else:
            manager.get(tunnel_id)
        server = MCPServerConfig(
            name=tunnel_id,
            transport="streamable_http",
            required=True,
            url=payload.url or _default_tunnel_mcp_url(request, tunnel_id),
            headers=headers,
            timeout=payload.timeout,
        )
        server.validate()
        result = await _runtime_manager(request).apply_mcp_server(server)
    except HTTPException:
        raise
    except TunnelNotConnectedError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{exc} Configure a local MCP profile, then apply it again.",
        ) from exc
    except (MCPConfigError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        bridge_status = _local_bridge_manager(request).status().get(tunnel_id, {})
        last_error = bridge_status.get("last_error")
        detail = str(exc)
        if last_error:
            detail = f"{detail} Last bridge error: {last_error}"
        raise HTTPException(status_code=503, detail=detail) from exc
    except Exception as exc:  # noqa: BLE001 - surface reload failure without swapping runtime.
        raise HTTPException(status_code=502, detail=_public_reload_error(exc, token)) from exc
    return result.as_dict()


@router.delete("/{tunnel_id}/agent-config")
async def remove_tunnel_agent_config(request: Request, tunnel_id: str) -> dict[str, Any]:
    try:
        await _local_bridge_manager(request).stop(tunnel_id)
        result = await _runtime_manager(request).remove_mcp_server(tunnel_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - keep prior runtime if rebuild fails.
        raise HTTPException(status_code=502, detail=_public_reload_error(exc, None)) from exc
    return result.as_dict()


@router.websocket("/{tunnel_id}/client")
async def tunnel_client(websocket: WebSocket, tunnel_id: str) -> None:
    if not _authorized(websocket.headers.get("authorization"), websocket.query_params.get("token")):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    connection = await manager.register(tunnel_id, websocket)
    try:
        while True:
            payload = await websocket.receive_json()
            if isinstance(payload, dict):
                await connection.handle_client_message(payload)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.unregister(tunnel_id, connection)


@router.post("/{tunnel_id}/mcp")
async def mcp_post(
    request: Request,
    tunnel_id: str,
    mcp_session_id: str | None = Header(default=None, alias=MCP_SESSION_ID_HEADER),
    authorization: str | None = Header(default=None),
) -> Response:
    _require_authorized(authorization, request.query_params.get("token"))
    message = await _read_jsonrpc_message(request)
    session_id = mcp_session_id or new_session_id()
    new_session = mcp_session_id is None and is_initialize_request(message)
    if mcp_session_id is None and not new_session:
        raise HTTPException(status_code=400, detail="Missing mcp-session-id header.")

    try:
        connection = manager.get(tunnel_id)
        if is_jsonrpc_request(message):
            response_message = await connection.forward_request(
                session_id=session_id,
                message=message,
                new_session=new_session,
            )
            headers = {MCP_SESSION_ID_HEADER: session_id} if new_session else None
            return JSONResponse(response_message, headers=headers)

        if is_jsonrpc_notification(message):
            await connection.forward_notification(
                session_id=session_id,
                message=message,
                new_session=new_session,
            )
            headers = {MCP_SESSION_ID_HEADER: session_id} if new_session else None
            return Response(status_code=202, headers=headers)
    except TunnelNotConnectedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TunnelRequestError as exc:
        if "id" in message:
            return JSONResponse(
                make_jsonrpc_error(request_id=message.get("id"), code=-32000, message=str(exc)),
                status_code=502,
            )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    raise HTTPException(status_code=400, detail="Expected a JSON-RPC request or notification.")


@router.get("/{tunnel_id}/mcp")
async def mcp_get(
    request: Request,
    tunnel_id: str,
    mcp_session_id: str | None = Header(default=None, alias=MCP_SESSION_ID_HEADER),
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    _require_authorized(authorization, request.query_params.get("token"))
    if not mcp_session_id:
        raise HTTPException(status_code=400, detail="Missing mcp-session-id header.")
    try:
        queue = manager.get(tunnel_id).notification_queue(mcp_session_id)
    except TunnelNotConnectedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return StreamingResponse(
        _sse_notifications(queue, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.delete("/{tunnel_id}/mcp")
async def mcp_delete(
    request: Request,
    tunnel_id: str,
    mcp_session_id: str | None = Header(default=None, alias=MCP_SESSION_ID_HEADER),
    authorization: str | None = Header(default=None),
) -> Response:
    _require_authorized(authorization, request.query_params.get("token"))
    if mcp_session_id:
        try:
            await manager.get(tunnel_id).close_session(mcp_session_id)
        except TunnelNotConnectedError:
            pass
    return Response(status_code=204)


async def _read_jsonrpc_message(request: Request) -> JSONRPCMessage:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Request body is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="JSON-RPC batch messages are not supported yet.",
        )
    if payload.get("jsonrpc") != "2.0":
        raise HTTPException(status_code=400, detail="Expected JSON-RPC 2.0 message.")
    return payload


async def _sse_notifications(
    queue,
    request: Request,
) -> AsyncIterator[str]:
    while not await request.is_disconnected():
        message = await queue.get()
        yield f"event: message\ndata: {json.dumps(message, separators=(',', ':'))}\n\n"


def _require_authorized(authorization: str | None, token: str | None) -> None:
    if not _authorized(authorization, token):
        raise HTTPException(status_code=401, detail="Invalid MCP tunnel token.")


def _authorized(authorization: str | None, token: str | None) -> bool:
    expected = os.environ.get(TUNNEL_AUTH_ENV, "").strip()
    if not expected:
        return True
    return _bearer_token(authorization) == expected or token == expected


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


def _runtime_manager(request: Request) -> AgentRuntimeManager:
    runtime_manager = getattr(request.app.state, "agent_runtime_manager", None)
    if runtime_manager is None:
        raise HTTPException(status_code=503, detail="Agent runtime manager is not available.")
    return runtime_manager


def _local_bridge_manager(request: Request) -> LocalBridgeManager:
    local_bridge_manager = getattr(request.app.state, "local_bridge_manager", None)
    if local_bridge_manager is None:
        raise HTTPException(status_code=503, detail="Local MCP bridge manager is not available.")
    return local_bridge_manager


def _default_tunnel_mcp_url(request: Request, tunnel_id: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/dev/mcp-tunnels/{quote(tunnel_id, safe='')}/mcp"


def _default_backend_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _has_local_bridge_profile(payload: TunnelAgentConfigRequest) -> bool:
    return bool(_optional_non_empty(payload.mcp_command) or _optional_non_empty(payload.mcp_config))


def _optional_non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _public_reload_error(exc: Exception, token: str | None) -> str:
    text = str(exc) or exc.__class__.__name__
    if token:
        text = text.replace(token, "[redacted]")
    return text
