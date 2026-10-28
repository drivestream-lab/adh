"""PostgreSQL database connection management."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.configs.postgres_settings import PostgresSettings
from src.logging import get_logger

logger = get_logger()


class PostgresConnectionManager:
    """Manager for PostgreSQL database connections."""

    def __init__(self) -> None:
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._settings = PostgresSettings.get_instance()

    async def initialize(self) -> None:
        """Initialize the database engine and session factory."""
        if self._engine is None:
            logger.info("Initializing PostgreSQL connection manager")
            url = self._settings.sqlalchemy_database_uri
            engine_args = self._settings.sqlalchemy_engine_args
            self._engine = create_async_engine(url, **engine_args)
            self._session_factory = async_sessionmaker(
                self._engine,
                expire_on_commit=False,
                autoflush=False,
                autocommit=False,
            )
            logger.info("PostgreSQL connection manager initialized successfully")

    async def close(self) -> None:
        """Close all database connections."""
        if self._engine:
            logger.info("Closing PostgreSQL database connections")
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("PostgreSQL database connections closed")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session. Commits on normal exit, rolls back on exception, then closes."""
        if self._session_factory is None:
            raise RuntimeError("PostgreSQL session factory has not been initialized")
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession, None]:
        """Start a database transaction."""
        async with self.get_session() as session:
            async with session.begin():
                yield session

    def get_engine(self) -> Optional[AsyncEngine]:
        """Return the async SQLAlchemy engine when initialized."""
        return self._engine

    async def health_check(self) -> bool:
        """Check database connectivity."""
        if self._engine is None:
            return False
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("PostgreSQL health check failed", error=str(e))
            return False
