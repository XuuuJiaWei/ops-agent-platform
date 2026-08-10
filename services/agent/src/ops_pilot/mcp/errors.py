"""MCP transport failure classification shared by lifecycle and retry modules."""

from __future__ import annotations

from typing import Any

import anyio
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED


def is_mcp_session_disconnect(exc: BaseException) -> bool:
    """Return whether an exception means the current MCP session is unusable."""

    if isinstance(exc, BaseExceptionGroup):
        return any(is_mcp_session_disconnect(child) for child in exc.exceptions)
    if isinstance(exc, McpError):
        error: Any = exc.error
        message = str(getattr(error, "message", "")).lower()
        return getattr(error, "code", None) == CONNECTION_CLOSED or "session terminated" in message
    return isinstance(
        exc,
        (anyio.BrokenResourceError, anyio.ClosedResourceError, anyio.EndOfStream),
    )


def is_mcp_shutdown_noise(exc: BaseException) -> bool:
    """Recognize expected transport/process errors emitted during teardown."""

    if isinstance(exc, BaseExceptionGroup):
        return all(is_mcp_shutdown_noise(child) for child in exc.exceptions)
    if isinstance(exc, (anyio.BrokenResourceError, anyio.ClosedResourceError, anyio.EndOfStream)):
        return True
    text = str(exc)
    return any(
        marker in text
        for marker in (
            "Received SIGTERM, terminating child process",
            "Child process terminated by signal: SIGTERM",
            "BrokenResourceError",
        )
    )
