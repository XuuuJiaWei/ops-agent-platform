import asyncio

import pytest

from ops_pilot.tunnel.manager import TunnelManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_forward_request_resolves_from_client_response() -> None:
    manager = TunnelManager()
    websocket = FakeWebSocket()
    connection = await manager.register("local", websocket)  # type: ignore[arg-type]

    task = asyncio.create_task(
        connection.forward_request(
            session_id="session-1",
            message={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    )
    await asyncio.sleep(0)

    outbound = websocket.sent[0]
    assert outbound["type"] == "mcp.request"
    assert outbound["sessionId"] == "session-1"
    assert outbound["message"]["method"] == "tools/list"

    await connection.handle_client_message(
        {
            "type": "mcp.response",
            "id": outbound["id"],
            "message": {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}},
        }
    )

    assert await task == {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}


@pytest.mark.asyncio
async def test_client_notifications_are_queued_by_session() -> None:
    manager = TunnelManager()
    connection = await manager.register("local", FakeWebSocket())  # type: ignore[arg-type]

    await connection.handle_client_message(
        {
            "type": "mcp.notification",
            "sessionId": "session-1",
            "message": {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"},
        }
    )

    queued = await connection.notification_queue("session-1").get()
    assert queued == {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
