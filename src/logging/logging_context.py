"""Logging context module for Parichay."""

import contextvars
import functools
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional, TypeVar

from loguru import logger

correlation_id_var = contextvars.ContextVar("correlation_id", default="")
F = TypeVar("F", bound=Callable[..., Any])


def get_correlation_id() -> str:
    """Get the current correlation ID from context."""
    return correlation_id_var.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID in the current context."""
    correlation_id_var.set(correlation_id)


def correlation_id(func: F) -> F:
    """Decorator to create and propagate correlation ID."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        current_id = get_correlation_id()
        if not current_id:
            current_id = str(uuid.uuid4())
            token = correlation_id_var.set(current_id)
            try:
                return func(*args, **kwargs)
            finally:
                correlation_id_var.reset(token)
        else:
            return func(*args, **kwargs)

    return wrapper  # type: ignore


class LoggingContext:
    """Context manager for setting correlation ID in logging context."""

    def __init__(self, correlation_id: Optional[str] = None):
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.token = None

    def __enter__(self):
        self.token = correlation_id_var.set(self.correlation_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token is not None:
            correlation_id_var.reset(self.token)


@contextmanager
def log_scope(**fields: Any) -> Iterator[None]:
    """Bind searchable log fields for the current scope (Airforge-style contextualize)."""
    bound = {key: str(value) for key, value in fields.items() if value is not None}
    if not bound:
        yield
        return
    with logger.contextualize(**bound):
        yield
