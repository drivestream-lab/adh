"""Redis connection manager for Parichay."""

from typing import Optional

from redis.asyncio import Redis

from src.configs.redis_settings import RedisSettings
from src.logging import get_logger

logger = get_logger()


class RedisConnectionManager:
    """Manage Redis connections for Parichay."""

    def __init__(self) -> None:
        self._client: Optional[Redis] = None
        self._initialized: bool = False
        self._settings = RedisSettings.get_instance()

    def initialize(self) -> None:
        """Initialize Redis connection."""
        if self._initialized:
            logger.debug("Redis connection manager already initialized")
            return

        logger.info("Initializing Redis connection manager")

        try:
            self._client = Redis(
                host=self._settings.host,
                port=self._settings.port,
                db=self._settings.db,
                password=(
                    self._settings.password.get_secret_value() if self._settings.password else None
                ),
                ssl=self._settings.use_ssl,
                socket_timeout=self._settings.socket_timeout,
                socket_connect_timeout=self._settings.connection_timeout,
                retry_on_timeout=self._settings.retry_on_timeout,
                max_connections=self._settings.pool_max_size,
                decode_responses=True,
            )

            self._initialized = True
            logger.info("Redis connection manager initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize Redis connection", error=str(e))
            if self._client:
                self._client = None
            raise

    async def close(self) -> None:
        """Close Redis connection and clean up resources."""
        if not self._initialized:
            logger.debug("Redis connection manager not initialized, nothing to close")
            return

        logger.info("Closing Redis connection manager")

        if self._client:
            await self._client.aclose()
            self._client = None

        self._initialized = False
        logger.info("Redis connection manager closed successfully")

    def get_client(self) -> Redis:
        """Get Redis client.

        Returns:
            Redis client

        Raises:
            RuntimeError: If connection manager is not initialized
        """
        if not self._initialized or self._client is None:
            logger.error("Redis connection manager not initialized")
            raise RuntimeError("Redis connection manager not initialized")

        return self._client

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set value in Redis.

        Args:
            key: Redis key
            value: Value to set
            ttl: Time to live in seconds, if None uses default TTL

        Returns:
            True if operation succeeded
        """
        ttl = ttl or self._settings.default_ttl
        client = self.get_client()

        try:
            return await client.set(key, value, ex=ttl)
        except Exception as e:
            logger.error("Failed to set Redis key", key=key, error=str(e))
            return False

    async def get(self, key: str) -> Optional[str]:
        """Get value from Redis.

        Args:
            key: Redis key

        Returns:
            Value or None if key doesn't exist
        """
        client = self.get_client()

        try:
            return await client.get(key)
        except Exception as e:
            logger.error("Failed to get Redis key", key=key, error=str(e))
            return None

    async def get_strict(self, key: str) -> Optional[str]:
        """Get key value; raises on Redis/client errors (missing key returns None)."""
        client = self.get_client()
        return await client.get(key)

    async def delete(self, key: str) -> int:
        """Delete key from Redis.

        Args:
            key: Redis key

        Returns:
            Number of keys deleted
        """
        client = self.get_client()

        try:
            return await client.delete(key)
        except Exception as e:
            logger.error("Failed to delete Redis key", key=key, error=str(e))
            return 0

    async def incr(self, key: str) -> int:
        """Atomically increment a key (creates at 1 if missing)."""
        client = self.get_client()
        try:
            return int(await client.incr(key))
        except Exception as e:
            logger.error("Failed to INCR Redis key", key=key, error=str(e))
            raise

    async def exists(self, key: str) -> bool:
        """Check if key exists in Redis.

        Args:
            key: Redis key

        Returns:
            True if key exists
        """
        client = self.get_client()

        try:
            result = await client.exists(key)
            return result > 0
        except Exception as e:
            logger.error("Failed to check if Redis key exists", key=key, error=str(e))
            return False

    async def health_check(self) -> bool:
        """Check if Redis is healthy.

        Returns:
            True if Redis is healthy
        """
        if not self._initialized or self._client is None:
            return False

        try:
            return await self._client.ping()
        except Exception as e:
            logger.error("Redis health check failed", error=str(e))
            return False
