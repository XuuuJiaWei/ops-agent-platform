"""In-memory connection manager for protocol-level MCP tunnels."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from ops_pilot.tunnel.schemas import JSONRPCMessage


class TunnelError(RuntimeError):
    """Base class for tunnel relay failures."""


class TunnelNotConnectedError(TunnelError):
    """Raised when an MCP request targets an offline tunnel."""


class TunnelRequestError(TunnelError):
    """Raised when a local tunnel-client reports a request failure."""


@dataclass
class TunnelConnection:
    tunnel_id: str
    websocket: WebSocket
    pending: dict[str, asyncio.Future[JSONRPCMessage]] = field(default_factory=dict)
    notifications: dict[str, asyncio.Queue[JSONRPCMessage]] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def forward_request(
        self,
        *,
        session_id: str,
        message: JSONRPCMessage,
        new_session: bool = False,
        timeout: float = 60.0,
    ) -> JSONRPCMessage:
        relay_id = _new_relay_id()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[JSONRPCMessage] = loop.create_future()
        self.pending[relay_id] = future

        await self._send(
            {
                "type": "mcp.request",
                "id": relay_id,
                "sessionId": session_id,
                "newSession": new_session,
                "message": message,
            }
        )

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.pending.pop(relay_id, None)

    async def forward_notification(
        self,
        *,
        session_id: str,
        message: JSONRPCMessage,
        new_session: bool = False,
    ) -> None:
        await self._send(
            {
                "type": "mcp.notification",
                "sessionId": session_id,
                "newSession": new_session,
                "message": message,
            }
        )

    async def close_session(self, session_id: str) -> None:
        await self._send({"type": "mcp.close_session", "sessionId": session_id})

    async def handle_client_message(self, payload: dict[str, Any]) -> None:
        message_type = payload.get("type")
        if message_type == "mcp.response":
            relay_id = str(payload.get("id", ""))
            future = self.pending.get(relay_id)
            if future is not None and not future.done():
                future.set_result(_require_message(payload.get("message")))
            return

        if message_type == "mcp.error":
            relay_id = str(payload.get("id", ""))
            future = self.pending.get(relay_id)
            if future is not None and not future.done():
                future.set_exception(
                    TunnelRequestError(str(payload.get("error") or "MCP tunnel error"))
                )
            return

        if message_type == "mcp.notification":
            session_id = str(payload.get("sessionId", ""))
            if session_id:
                message = _require_message(payload.get("message"))
                await self.notification_queue(session_id).put(message)

    def notification_queue(self, session_id: str) -> asyncio.Queue[JSONRPCMessage]:
        queue = self.notifications.get(session_id)
        if queue is None:
            queue = asyncio.Queue()
            self.notifications[session_id] = queue
        return queue

    async def fail_pending(self, exc: BaseException) -> None:
        for future in list(self.pending.values()):
            if not future.done():
                future.set_exception(exc)
        self.pending.clear()

    async def _send(self, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send_json(payload)


class TunnelManager:
    def __init__(self) -> None:
        self._connections: dict[str, TunnelConnection] = {}
        self._lock = asyncio.Lock()

    async def register(self, tunnel_id: str, websocket: WebSocket) -> TunnelConnection:
        connection = TunnelConnection(tunnel_id=tunnel_id, websocket=websocket)
        async with self._lock:
            old = self._connections.get(tunnel_id)
            self._connections[tunnel_id] = connection
        if old is not None:
            await old.fail_pending(TunnelNotConnectedError("Tunnel client was replaced."))
        return connection

    async def unregister(self, tunnel_id: str, connection: TunnelConnection) -> None:
        async with self._lock:
            if self._connections.get(tunnel_id) is connection:
                self._connections.pop(tunnel_id, None)
        await connection.fail_pending(TunnelNotConnectedError("Tunnel client disconnected."))

    def get(self, tunnel_id: str) -> TunnelConnection:
        connection = self._connections.get(tunnel_id)
        if connection is None:
            raise TunnelNotConnectedError(f"Tunnel '{tunnel_id}' is not connected.")
        return connection

    def status(self) -> dict[str, Any]:
        return {
            tunnel_id: {
                "connected": True,
                "pending": len(connection.pending),
                "sessions": sorted(connection.notifications.keys()),
            }
            for tunnel_id, connection in sorted(self._connections.items())
        }


manager = TunnelManager()


def _new_relay_id() -> str:
    return f"relay_{uuid.uuid4().hex}"


def new_session_id() -> str:
    return f"mcp_sess_{uuid.uuid4().hex}"


def _require_message(value: Any) -> JSONRPCMessage:
    if not isinstance(value, dict):
        raise TunnelRequestError("Tunnel payload did not include a JSON-RPC object.")
    return value
