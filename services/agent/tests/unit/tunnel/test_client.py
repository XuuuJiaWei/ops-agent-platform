import asyncio
import sys
from pathlib import Path

import pytest

from ops_pilot.tunnel.client import LocalMCPSession, TunnelClientConfig


@pytest.mark.asyncio
async def test_local_stdio_session_routes_response_to_relay_id(tmp_path: Path) -> None:
    server = tmp_path / "fake_mcp.py"
    server.write_text(
        """
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    if 'id' in message:
        response = {'jsonrpc': '2.0', 'id': message['id'], 'result': {'ok': True}}
        sys.stdout.write(json.dumps(response) + '\\n')
        sys.stdout.flush()
""".strip(),
        encoding="utf-8",
    )
    sent: list[dict] = []

    async def send(payload: dict) -> None:
        sent.append(payload)

    session = LocalMCPSession(
        session_id="session-1",
        command=[sys.executable, str(server)],
        cwd=None,
        env={},
        send=send,
        on_exit=lambda: None,
    )
    await session.start()
    try:
        await session.write_message(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
            relay_id="relay-1",
        )
        for _ in range(20):
            if sent:
                break
            await asyncio.sleep(0.05)
        assert sent == [
            {
                "type": "mcp.response",
                "id": "relay-1",
                "message": {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}},
            }
        ]
    finally:
        await session.close()


def test_tunnel_client_config_builds_websocket_url() -> None:
    config = TunnelClientConfig(
        server_url="https://ops.example.com/api",
        tunnel_id="local dev",
        token="secret token",
        mcp_command="python server.py",
    )

    assert config.websocket_url() == ("wss://ops.example.com/api/dev/mcp-tunnels/local%20dev/client?token=secret+token")
