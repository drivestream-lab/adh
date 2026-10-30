"""Correlation ID middleware for Parichay."""

import time
import uuid
from typing import Any

from opentelemetry import trace
from starlette.types import ASGIApp, Receive, Scope, Send

from src.logging import get_logger, set_correlation_id

logger = get_logger()

_HEADER_NAME = "X-Correlation-ID"


def _resolve_correlation_id(headers: list[tuple[bytes, bytes]]) -> str:
    """Assign one correlation ID per request from the canonical header or a new UUID."""
    for key, value in headers:
        if key.decode("latin-1").lower() == _HEADER_NAME.lower():
            text = value.decode("latin-1").strip()
            if text:
                return text
    return str(uuid.uuid4())


def _set_correlation_on_span(correlation_id: str) -> None:
    """Stamp Loguru correlation_id onto the active OTel span for logs-traces linking."""
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("correlation_id", correlation_id)


class CorrelationIdMiddleware:
    """Pure ASGI tracing boundary. Must not use BaseHTTPMiddleware — that buffers SSE."""

    def __init__(self, app: ASGIApp, header_name: str = _HEADER_NAME) -> None:
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = _resolve_correlation_id(list(scope.get("headers") or []))
        scope.setdefault("state", {})
        scope["state"]["correlation_id"] = correlation_id
        set_correlation_id(correlation_id)
        _set_correlation_on_span(correlation_id)

        start_time = time.time()
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "")
        logger.debug(
            "Request started",
            method=method,
            path=path,
            correlation_id=correlation_id,
        )

        async def send_with_header(message: Any) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append(
                    (self.header_name.lower().encode("latin-1"), correlation_id.encode("latin-1"))
                )
                message = {**message, "headers": headers}
                _set_correlation_on_span(correlation_id)
                logger.debug(
                    "Request completed",
                    method=method,
                    path=path,
                    duration_seconds=round(time.time() - start_time, 3),
                    correlation_id=correlation_id,
                )
            await send(message)

        await self.app(scope, receive, send_with_header)
