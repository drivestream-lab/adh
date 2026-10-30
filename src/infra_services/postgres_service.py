"""PostgreSQL database service for Parichay."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, cast

from injector import inject
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.postgres.connection_manager import PostgresConnectionManager
from src.di.qualified_types import PostgresSessionFactory
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger

logger = get_logger()


class PostgresService(BaseInfraService):
    """Service for interacting with PostgreSQL database."""

    @inject
    def __init__(self, connection_manager: PostgresConnectionManager) -> None:
        super().__init__()
        self._connection_manager = connection_manager
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the PostgreSQL service."""
        if not self._initialized:
            logger.info("Initializing PostgreSQL service")
            await self._connection_manager.initialize()
            self._initialized = True
            logger.info("PostgreSQL service initialized successfully")

    async def close(self) -> None:
        """Close the PostgreSQL service."""
        if self._initialized:
            logger.info("Closing PostgreSQL service")
            await self._connection_manager.close()
            self._initialized = False
            logger.info("PostgreSQL service closed")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session."""
        if not self._initialized:
            raise RuntimeError("PostgreSQL service has not been initialized")
        async with self._require_connection_manager().get_session() as session:
            yield session

    def get_session_factory(self) -> PostgresSessionFactory:
        """Get the session factory for repositories."""
        if not self._initialized:
            raise RuntimeError("PostgreSQL service has not been initialized")
        return cast(PostgresSessionFactory, self._require_connection_manager().get_session)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession, None]:
        """Start a database transaction."""
        if not self._initialized:
            raise RuntimeError("PostgreSQL service has not been initialized")
        async with self._require_connection_manager().transaction() as session:
            yield session

    def _require_connection_manager(self) -> PostgresConnectionManager:
        if not self._initialized:
            raise RuntimeError("PostgreSQL service has not been initialized")
        return self._connection_manager

    async def health_check(self) -> bool:
        """Check database connectivity."""
        if not self._initialized:
            return False
        try:
            async with self._require_connection_manager().get_session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("Health check failed: could not connect to database")
            return False


def get_postgres_service() -> PostgresService:
    """Get the PostgreSQL service instance."""
    from src.di.dependency_container import provide_service

    return provide_service(PostgresService)
