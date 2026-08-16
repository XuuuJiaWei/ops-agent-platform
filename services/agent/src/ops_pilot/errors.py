"""Shared exception policy for runtime dependencies and host adapters.

The module keeps three decisions together: the client-safe error contract, the
HTTP status, and whether an exception deserves a traceback.  Callers only need
to describe or log an exception; they do not repeat classification rules.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ErrorDescriptor:
    """Stable public and operational treatment for one exception category."""

    code: str
    message: str
    http_status: int
    log_level: int
    include_traceback: bool


_INTERNAL_ERROR = ErrorDescriptor(
    code="internal_error",
    message="Unexpected server error.",
    http_status=500,
    log_level=logging.ERROR,
    include_traceback=True,
)
_SANDBOX_UNAVAILABLE = ErrorDescriptor(
    code="sandbox_unavailable",
    message="The sandbox expired or became unavailable. Please retry; a fresh sandbox will be created automatically.",
    http_status=503,
    log_level=logging.WARNING,
    include_traceback=False,
)
_MODEL_UNAVAILABLE = ErrorDescriptor(
    code="model_unavailable",
    message=(
        "The configured AI model is temporarily unreachable. "
        "Check the model endpoint, proxy, and TLS settings, then retry."
    ),
    http_status=503,
    log_level=logging.WARNING,
    include_traceback=False,
)
_UPSTREAM_TIMEOUT = ErrorDescriptor(
    code="upstream_timeout",
    message="A required upstream service timed out. Please retry.",
    http_status=504,
    log_level=logging.WARNING,
    include_traceback=False,
)
_DEPENDENCY_UNAVAILABLE = ErrorDescriptor(
    code="dependency_unavailable",
    message="A required upstream service is temporarily unavailable. Please retry.",
    http_status=503,
    log_level=logging.WARNING,
    include_traceback=False,
)

_MODEL_CONNECTION_ERRORS = {"APIConnectionError", "APITimeoutError"}
_TIMEOUT_ERRORS = {"ConnectTimeout", "PoolTimeout", "ReadTimeout", "WriteTimeout"}
_CONNECTION_ERRORS = {"ConnectError", "NetworkError", "RemoteProtocolError"}
_MCP_HTTP_LOGGER = "mcp.client.streamable_http"


def describe_exception(exc: BaseException) -> ErrorDescriptor:
    """Classify an exception without exposing implementation details."""

    chain = tuple(iter_exception_chain(exc))
    names = {item.__class__.__name__ for item in chain}
    text = "\n".join(str(item).lower() for item in chain)
    if "sandbox" in text and any(marker in text for marker in ("not found", "status code: 404")):
        return _SANDBOX_UNAVAILABLE
    if names & _MODEL_CONNECTION_ERRORS:
        return _MODEL_UNAVAILABLE
    if any(isinstance(item, TimeoutError) for item in chain) or names & _TIMEOUT_ERRORS:
        return _UPSTREAM_TIMEOUT
    if any(isinstance(item, ConnectionError) for item in chain) or names & _CONNECTION_ERRORS:
        return _DEPENDENCY_UNAVAILABLE
    return _INTERNAL_ERROR


def public_error_payload(exc: BaseException) -> dict[str, str]:
    """Return the stable, client-safe error fields shared by all protocols."""

    descriptor = describe_exception(exc)
    return {"code": descriptor.code, "message": descriptor.message}


def log_exception(
    logger: logging.Logger,
    exc: BaseException,
    *,
    event: str,
    **context: Any,
) -> ErrorDescriptor:
    """Log an exception once according to policy and return its descriptor.

    Expected operational failures are concise warnings. Unknown failures keep
    their traceback because they may indicate a programming defect.
    """

    descriptor = describe_exception(exc)
    fields = {
        "event_name": event,
        "error_code": descriptor.code,
        "error_type": exc.__class__.__name__,
        **context,
    }
    context_text = " ".join(f"{key}={value}" for key, value in context.items() if value is not None)
    message = f"{event} code={descriptor.code} error_type={exc.__class__.__name__}"
    if context_text:
        message = f"{message} {context_text}"
    if not descriptor.include_traceback:
        summary = safe_exception_summary(exc)
        if summary:
            message = f"{message} detail={summary}"
    logger.log(
        descriptor.log_level,
        message,
        extra=fields,
        exc_info=_exception_info(exc) if descriptor.include_traceback else None,
    )
    return descriptor


def safe_exception_summary(exc: BaseException, *, limit: int = 500) -> str:
    """Build a one-line, secret-redacted summary for operational logs."""

    chain = tuple(iter_exception_chain(exc))
    parts = [str(item).strip() or item.__class__.__name__ for item in chain if not isinstance(item, BaseExceptionGroup)]
    if not parts:
        parts = [str(exc).strip() or exc.__class__.__name__]
    text = " <- ".join(dict.fromkeys(parts))
    for key, value in os.environ.items():
        if _looks_secret(key) and value:
            text = text.replace(value, "[redacted]")
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def configure_exception_logging() -> None:
    """Collapse known MCP transport noise while preserving unexpected traces."""

    dependency_logger = logging.getLogger(_MCP_HTTP_LOGGER)
    if not any(isinstance(item, _MCPTransportFilter) for item in dependency_logger.filters):
        dependency_logger.addFilter(_MCPTransportFilter())


def iter_exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield causes, contexts, and exception-group children once each."""

    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        if isinstance(current, BaseExceptionGroup):
            pending[0:0] = list(current.exceptions)
        chained = current.__cause__ or current.__context__
        if chained is not None:
            pending.append(chained)


def _exception_info(exc: BaseException) -> tuple[type[BaseException], BaseException, Any]:
    return type(exc), exc, exc.__traceback__


def _looks_secret(key: str) -> bool:
    key_upper = key.upper()
    return any(marker in key_upper for marker in ("TOKEN", "SECRET", "PASSWORD", "AUTH", "KEY", "CREDENTIAL"))


class _MCPTransportFilter(logging.Filter):
    """Normalize known transport failures emitted inside the upstream MCP SDK."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if message == "Session termination failed: 404":
            return False
        if not message.startswith("Error in post_writer") or not record.exc_info:
            return True
        exc = record.exc_info[1]
        if not isinstance(exc, BaseException):
            return True
        descriptor = describe_exception(exc)
        if descriptor.include_traceback:
            return True
        record.msg = (
            f"mcp.transport_failed code={descriptor.code} "
            f"error_type={exc.__class__.__name__} detail={safe_exception_summary(exc)}"
        )
        record.args = ()
        record.levelno = logging.WARNING
        record.levelname = logging.getLevelName(logging.WARNING)
        record.exc_info = None
        record.exc_text = None
        record.error_code = descriptor.code
        record.event_name = "mcp.transport_failed"
        return True
