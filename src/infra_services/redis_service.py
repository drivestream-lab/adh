"""Redis service implementation for Parichay."""

import json
from typing import Any, Optional

from injector import inject
from redis.asyncio import Redis

from src.database.redis.connection_manager import RedisConnectionManager
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger

logger = get_logger()


class RedisService(BaseInfraService):
    """Service for interacting with Redis.

    Provides caching, ACL cache, and session management for Parichay.
    """

    @inject
    def __init__(self, connection_manager: RedisConnectionManager) -> None:
        """Initialize the Redis service."""
        super().__init__()
        self._connection_manager = connection_manager
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the Redis service."""
        if not self._initialized:
            logger.info("Initializing Redis service")
            self._connection_manager.initialize()
            self._initialized = True
            logger.info("Redis service initialized successfully")

    async def close(self) -> None:
        """Close the Redis service."""
        if self._initialized:
            logger.info("Closing Redis service")
            await self._connection_manager.close()
            self._initialized = False
            logger.info("Redis service closed")

    def get_client(self) -> Redis:
        """Get the Redis client.

        Returns:
            Redis client

        Raises:
            RuntimeError: If the service has not been initialized
        """
        if not self._initialized:
            raise RuntimeError("Redis service has not been initialized")

        return self._require_connection_manager().get_client()

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set a value in Redis.

        Args:
            key: Redis key
            value: Value to set (will be JSON serialized if not a string)
            ttl: Time to live in seconds

        Returns:
            True if operation succeeded
        """
        if not self._initialized:
            raise RuntimeError("Redis service has not been initialized")

        if not isinstance(value, str):
            value = json.dumps(value)

        return await self._require_connection_manager().set(key, value, ttl)

    async def get(self, key: str, as_json: bool = False) -> Any:
        """Get a value from Redis.

        Args:
            key: Redis key
            as_json: If True, attempt to parse the value as JSON

        Returns:
            Value from Redis or None if key doesn't exist
        """
        if not self._initialized:
            raise RuntimeError("Redis service has not been initialized")

        value = await self._require_connection_manager().get(key)

        if value and as_json:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to parse Redis value as JSON",
                    redis_key=key,
                )
                return value

        return value

    async def get_strict(self, key: str) -> Optional[str]:
        """Get a value; propagates Redis errors (for fail-closed callers such as EMQX ACL cache)."""
        if not self._initialized:
            raise RuntimeError("Redis service has not been initialized")
        return await self._require_connection_manager().get_strict(key)

    async def delete(self, key: str) -> int:
        """Delete a key from Redis.

        Args:
            key: Redis key

        Returns:
            Number of keys deleted
        """
        if not self._initialized:
            raise RuntimeError("Redis service has not been initialized")

        return await self._require_connection_manager().delete(key)

    async def incr(self, key: str) -> int:
        """Atomically increment a key (creates at 1 if missing)."""
        if not self._initialized:
            raise RuntimeError("Redis service has not been initialized")
        return await self._require_connection_manager().incr(key)

    async def exists(self, key: str) -> bool:
        """Check if a key exists in Redis.

        Args:
            key: Redis key

        Returns:
            True if key exists
        """
        if not self._initialized:
            raise RuntimeError("Redis service has not been initialized")

        return await self._require_connection_manager().exists(key)

    async def health_check(self) -> bool:
        """Check Redis connectivity.

        Returns:
            True if Redis is accessible, False otherwise
        """
        if not self._initialized:
            return False

        return await self._require_connection_manager().health_check()

    def _require_connection_manager(self) -> RedisConnectionManager:
        if not self._initialized:
            raise RuntimeError("Redis service has not been initialized")
        return self._connection_manager