"""Correlation ID middleware for Parichay."""

import time
import uuid

from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.logging import get_logger, set_correlation_id

logger = get_logger()

_HEADER_NAME = "X-Correlation-ID"


def _resolve_correlation_id(request: Request) -> str:
    """Assign one correlation ID per request from the canonical header or a new UUID."""
    header_value = request.headers.get(_HEADER_NAME, "").strip()
    if header_value:
        return header_value
    return str(uuid.uuid4())


def _set_correlation_on_span(correlation_id: str) -> None:
    """Stamp Loguru correlation_id onto the active OTel span for logs-traces linking."""
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("correlation_id", correlation_id)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Single HTTP tracing boundary: one correlation ID per request for logs and responses."""

    def __init__(self, app, header_name: str = _HEADER_NAME) -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = _resolve_correlation_id(request)
        request.state.correlation_id = correlation_id
        set_correlation_id(correlation_id)
        _set_correlation_on_span(correlation_id)

        start_time = time.time()
        logger.debug(
            "Request started",
            method=request.method,
            path=request.url.path,
            correlation_id=correlation_id,
        )

        response = await call_next(request)
        _set_correlation_on_span(correlation_id)

        duration_seconds = round(time.time() - start_time, 3)
        logger.debug(
            "Request completed",
            method=request.method,
            path=request.url.path,
            duration_seconds=duration_seconds,
            correlation_id=correlation_id,
        )

        response.headers[self.header_name] = correlation_id
        return response
