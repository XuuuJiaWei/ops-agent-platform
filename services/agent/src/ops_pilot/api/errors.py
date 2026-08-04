"""HTTP exception handling helpers for ops_pilot FastAPI apps."""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Install stable JSON handling for unexpected non-streaming errors."""

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        logger.exception(
            "Unhandled HTTP exception request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": _error_code(exc),
                    "message": _public_error_message(exc),
                    "request_id": request_id,
                }
            },
            headers={"x-request-id": request_id},
        )


def stream_error_payload(exc: Exception) -> dict[str, str]:
    """Return client-safe error details for streaming protocol events."""

    return {
        "code": _error_code(exc),
        "message": _public_error_message(exc),
    }


def _request_id(request: Request) -> str:
    header = request.headers.get("x-request-id")
    return header.strip() if header and header.strip() else str(uuid4())


def _error_code(exc: Exception) -> str:
    if _is_sandbox_unavailable(exc):
        return "sandbox_unavailable"
    return "internal_error"


def _public_error_message(exc: Exception) -> str:
    if _is_sandbox_unavailable(exc):
        return "The sandbox expired or became unavailable. Please retry; a fresh sandbox will be created automatically."
    return "Unexpected server error."


def _is_sandbox_unavailable(exc: Exception) -> bool:
    text = _exception_text(exc)
    return "sandbox" in text and any(marker in text for marker in ("not found", "status code: 404"))


def _exception_text(exc: BaseException) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        parts.append(str(current).lower())
        current = current.__cause__ or current.__context__
    return "\n".join(parts)
