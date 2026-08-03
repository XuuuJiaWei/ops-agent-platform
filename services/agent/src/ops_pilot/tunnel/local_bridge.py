"""Local bridge lifecycle for developer-mode MCP tunnels.

This mirrors the product shape of Secure MCP Tunnel: users configure a local
profile, while a managed local client keeps the outbound tunnel connected.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any

from ops_pilot.tunnel.client import LocalTunnelClient, TunnelClientConfig
from ops_pilot.tunnel.manager import TunnelManager
from ops_pilot.tunnel.profile import resolve_tunnel_mcp_spec


@dataclass(frozen=True)
class LocalBridgeConfig:
    tunnel_id: str
    server_url: str
    token: str | None = None
    mcp_command: str | None = None
    mcp_config: str | None = None
    mcp_server: str | None = None
    cwd: str | None = None

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload.get("token"):
            payload["token"] = "[redacted]"
        return payload


@dataclass
class LocalBridgeHandle:
    config: LocalBridgeConfig
    task: asyncio.Task[None]
    running: bool = True
    last_error: str | None = None

    def as_dict(self, *, connected: bool) -> dict[str, Any]:
        return {
            "running": self.running and not self.task.done(),
            "connected": connected,
            "last_error": self.last_error,
            "config": self.config.public_dict(),
        }


class LocalBridgeManager:
    def __init__(self, tunnel_manager: TunnelManager) -> None:
        self._tunnel_manager = tunnel_manager
        self._bridges: dict[str, LocalBridgeHandle] = {}
        self._lock = asyncio.Lock()

    async def start(self, config: LocalBridgeConfig) -> LocalBridgeHandle:
        if not config.tunnel_id.strip():
            raise ValueError("Tunnel ID is required.")
        resolved = _to_client_config(config)
        async with self._lock:
            existing = self._bridges.get(config.tunnel_id)
            if existing is not None and existing.config == config and not existing.task.done():
                return existing
            if existing is not None:
                await self._stop_handle(config.tunnel_id, existing)

            handle = LocalBridgeHandle(
                config=config,
                task=asyncio.create_task(self._run_loop(resolved)),
            )
            self._bridges[config.tunnel_id] = handle
            return handle

    async def stop(self, tunnel_id: str) -> None:
        async with self._lock:
            handle = self._bridges.pop(tunnel_id, None)
            if handle is not None:
                await self._stop_handle(tunnel_id, handle)

    async def wait_connected(self, tunnel_id: str, *, timeout: float = 10.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if self._is_connected(tunnel_id):
                return
            handle = self._bridges.get(tunnel_id)
            if handle is not None and handle.task.done():
                detail = handle.last_error or "Local MCP bridge stopped before connecting."
                raise RuntimeError(detail)
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"Timed out waiting for local MCP bridge '{tunnel_id}' to connect.")
            await asyncio.sleep(0.1)

    def status(self) -> dict[str, Any]:
        return {
            tunnel_id: handle.as_dict(connected=self._is_connected(tunnel_id))
            for tunnel_id, handle in sorted(self._bridges.items())
        }

    async def shutdown(self) -> None:
        async with self._lock:
            items = list(self._bridges.items())
            self._bridges.clear()
        for tunnel_id, handle in items:
            await self._stop_handle(tunnel_id, handle)

    async def _run_loop(self, config: TunnelClientConfig) -> None:
        backoff = 0.5
        while True:
            client = LocalTunnelClient(config)
            try:
                await client.run()
                backoff = 0.5
            except asyncio.CancelledError:
                await client.close()
                raise
            except Exception as exc:  # noqa: BLE001 - bridge must keep retrying.
                self._record_error(config.tunnel_id, _public_error(exc, config.token))
                await client.close()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5.0)

    async def _stop_handle(self, tunnel_id: str, handle: LocalBridgeHandle) -> None:
        handle.running = False
        handle.task.cancel()
        try:
            await handle.task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 - stopping should be best effort.
            handle.last_error = _public_error(exc, handle.config.token)
        try:
            await self._tunnel_manager.get(tunnel_id).fail_pending(RuntimeError("Local MCP bridge stopped."))
        except Exception:
            pass

    def _record_error(self, tunnel_id: str, error: str) -> None:
        handle = self._bridges.get(tunnel_id)
        if handle is not None:
            handle.last_error = error

    def _is_connected(self, tunnel_id: str) -> bool:
        try:
            self._tunnel_manager.get(tunnel_id)
        except Exception:
            return False
        return True


def _to_client_config(config: LocalBridgeConfig) -> TunnelClientConfig:
    spec = resolve_tunnel_mcp_spec(
        mcp_command=config.mcp_command,
        mcp_config=config.mcp_config,
        mcp_server=config.mcp_server,
    )
    return TunnelClientConfig(
        server_url=config.server_url,
        tunnel_id=config.tunnel_id,
        token=config.token,
        mcp_command=spec.command,
        cwd=config.cwd,
        env=spec.env,
    )


def _public_error(exc: Exception, token: str | None) -> str:
    text = str(exc) or exc.__class__.__name__
    if token:
        text = text.replace(token, "[redacted]")
    return text
