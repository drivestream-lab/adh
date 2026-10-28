"""Qualified types for dependency injection."""

from typing import AsyncContextManager, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class PostgresSessionFactory(Protocol):
    """Callable that yields an async SQLAlchemy session context manager."""

    def __call__(self) -> AsyncContextManager[AsyncSession]: ...
