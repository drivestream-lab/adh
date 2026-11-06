"""Retry short-lived network failures before giving up."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Optional, TypeVar

import httpx

from src.logging import get_logger

logger = get_logger()

T = TypeVar("T")

OnAttempt = Callable[[int, int, BaseException], Awaitable[None]]

_TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def is_transient_error(exc: BaseException) -> bool:
    """True for connection/timeout blips and common gateway statuses."""
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
        ),
    ):
        return True
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return int(exc.response.status_code) in _TRANSIENT_STATUS
    # httpcore / nested OSError wrapped by httpx
    text = f"{type(exc).__name__}: {exc}".lower()
    if "connection" in text and ("failed" in text or "refused" in text or "reset" in text):
        return True
    return False


async def retry_transient(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    backoff_seconds: float = 2.0,
    label: str = "network",
    on_attempt: Optional[OnAttempt] = None,
) -> T:
    """Run ``operation`` up to ``attempts`` times on transient failures.

    Non-transient errors raise immediately. Exhausted transient failures re-raise
    the last exception.
    """
    max_attempts = max(1, int(attempts))
    delay = max(0.05, float(backoff_seconds))
    last: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except BaseException as exc:  # noqa: BLE001 — classify then re-raise
            if not is_transient_error(exc):
                raise
            last = exc
            if attempt >= max_attempts:
                logger.warning(
                    "Transient failure exhausted retries",
                    label=label,
                    attempt=attempt,
                    attempts=max_attempts,
                    error=str(exc)[:200],
                )
                raise
            logger.info(
                "Transient failure — retrying",
                label=label,
                attempt=attempt,
                attempts=max_attempts,
                error=str(exc)[:200],
                backoff_seconds=delay,
            )
            if on_attempt is not None:
                await on_attempt(attempt, max_attempts, exc)
            await asyncio.sleep(delay)
            delay *= 2
    assert last is not None
    raise last
