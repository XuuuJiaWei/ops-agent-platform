"""FastAPI adapter for the shared ops_pilot exception policy."""

from __future__ import annotations

import logging
import re
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ops_pilot.errors import configure_exception_logging, log_exception

logger = logging.getLogger(__name__)

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def register_exception_handlers(app: FastAPI) -> None:
    """Install request correlation and stable handling for HTTP errors."""

    configure_exception_logging()

    @app.middleware("http")
    async def correlate_request(request: Request, call_next):
        request_id = _request_id(request)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers.setdefault("x-request-id", request_id)
        return response

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        descriptor = log_exception(
            logger,
            exc,
            event="http.request_failed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=descriptor.http_status,
            content={
                "error": {
                    "code": descriptor.code,
                    "message": descriptor.message,
                    "request_id": request_id,
                }
            },
            headers={"x-request-id": request_id},
        )


def _request_id(request: Request) -> str:
    state_request_id = getattr(request.state, "request_id", None)
    if isinstance(state_request_id, str):
        return state_request_id
    header = request.headers.get("x-request-id", "").strip()
    return header if _REQUEST_ID_PATTERN.fullmatch(header) else str(uuid4())
