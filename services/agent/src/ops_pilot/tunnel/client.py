"""Local stdio MCP tunnel client."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import websockets

from ops_pilot.tunnel.schemas import JSONRPCMessage


@dataclass
class TunnelClientConfig:
    server_url: str
    tunnel_id: str
    mcp_command: str
    token: str | None = None
    cwd: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)

    def websocket_url(self) -> str:
        parsed = urlsplit(self.server_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        base_path = parsed.path.rstrip("/")
        tunnel_path = f"{base_path}/dev/mcp-tunnels/{quote(self.tunnel_id)}/client"
        query = urlencode({"token": self.token}) if self.token else ""
        return urlunsplit((scheme, parsed.netloc, tunnel_path, query, ""))


class LocalTunnelClient:
    def __init__(self, config: TunnelClientConfig) -> None:
        self.config = config
        self.sessions: dict[str, LocalMCPSession] = {}
        self.send_lock = asyncio.Lock()

    async def run(self) -> None:
        headers = {"Authorization": f"Bearer {self.config.token}"} if self.config.token else None
        async with websockets.connect(
            self.config.websocket_url(),
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=20,
        ) as websocket:
            print(f"Connected MCP tunnel '{self.config.tunnel_id}'.", file=sys.stderr)
            async for raw in websocket:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    await self._handle_gateway_message(websocket, payload)

    async def close(self) -> None:
        for session in list(self.sessions.values()):
            await session.close()
        self.sessions.clear()

    async def _handle_gateway_message(self, websocket: Any, payload: dict[str, Any]) -> None:
        message_type = payload.get("type")
        session_id = str(payload.get("sessionId") or "")
        if message_type == "mcp.close_session" and session_id:
            await self._close_session(session_id)
            return

        if message_type not in {"mcp.request", "mcp.notification"} or not session_id:
            return

        relay_id = str(payload.get("id") or "")
        try:
            session = await self._session(session_id, bool(payload.get("newSession")), websocket)
            await session.write_message(
                _require_message(payload.get("message")),
                relay_id=relay_id or None,
            )
        except Exception as exc:  # noqa: BLE001 - serialize local failures to gateway.
            if relay_id:
                await self._send(
                    websocket,
                    {"type": "mcp.error", "id": relay_id, "error": str(exc)},
                )

    async def _session(
        self,
        session_id: str,
        new_session: bool,
        websocket: Any,
    ) -> LocalMCPSession:
        existing = self.sessions.get(session_id)
        if existing is not None:
            return existing
        if not new_session:
            raise RuntimeError(f"Unknown MCP tunnel session: {session_id}")
        session = LocalMCPSession(
            session_id=session_id,
            command=shlex.split(self.config.mcp_command),
            cwd=self.config.cwd,
            env=self.config.env,
            send=lambda payload: self._send(websocket, payload),
            on_exit=lambda: self.sessions.pop(session_id, None),
        )
        await session.start()
        self.sessions[session_id] = session
        return session

    async def _close_session(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session is not None:
            await session.close()

    async def _send(self, websocket: Any, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            await websocket.send(json.dumps(payload, separators=(",", ":")))


class LocalMCPSession:
    def __init__(
        self,
        *,
        session_id: str,
        command: list[str],
        cwd: str | None,
        env: Mapping[str, str],
        send,
        on_exit,
    ) -> None:
        if not command:
            raise ValueError("MCP command cannot be empty.")
        self.session_id = session_id
        self.command = command
        self.cwd = cwd
        self.env = env
        self._send = send
        self._on_exit = on_exit
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[str, str] = {}
        self._write_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        env = {**os.environ, **self.env} if self.env else None
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def write_message(self, message: JSONRPCMessage, *, relay_id: str | None) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise RuntimeError("MCP process stdin is closed.")
        if relay_id and "id" in message:
            self._pending[_jsonrpc_id_key(message.get("id"))] = relay_id
        raw = json.dumps(message, separators=(",", ":")) + "\n"
        async with self._write_lock:
            process.stdin.write(raw.encode("utf-8"))
            await process.stdin.drain()

    async def close(self) -> None:
        process = self._process
        self._process = None
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def _read_stdout(self) -> None:
        process = self._require_process()
        assert process.stdout is not None
        try:
            while line := await process.stdout.readline():
                message = json.loads(line.decode("utf-8"))
                if not isinstance(message, dict):
                    continue
                await self._handle_mcp_output(message)
        finally:
            self._on_exit()

    async def _read_stderr(self) -> None:
        process = self._require_process()
        assert process.stderr is not None
        while line := await process.stderr.readline():
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                print(f"[{self.session_id}] {text}", file=sys.stderr)

    async def _handle_mcp_output(self, message: JSONRPCMessage) -> None:
        if "id" in message:
            relay_id = self._pending.pop(_jsonrpc_id_key(message.get("id")), None)
            if relay_id is not None:
                await self._send({"type": "mcp.response", "id": relay_id, "message": message})
            return
        if isinstance(message.get("method"), str):
            await self._send(
                {
                    "type": "mcp.notification",
                    "sessionId": self.session_id,
                    "message": message,
                }
            )

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise RuntimeError("MCP process is not running.")
        return self._process


def _jsonrpc_id_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _require_message(value: Any) -> JSONRPCMessage:
    if not isinstance(value, dict):
        raise ValueError("Expected JSON-RPC object from tunnel gateway.")
    return value


async def run_local_tunnel_client(config: TunnelClientConfig) -> None:
    client = LocalTunnelClient(config)
    try:
        await client.run()
    finally:
        await client.close()
