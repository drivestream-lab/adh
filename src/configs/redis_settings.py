"""Redis settings module for Parichay."""

from typing import Dict, Optional

from pydantic import Field, SecretStr, computed_field

from src.configs.base_settings import BaseSettings


class RedisSettings(BaseSettings):
    """Settings for Redis connection.

    Environment variables (with REDIS_ prefix):
    - REDIS_HOST: Redis server host
    - REDIS_PORT: Redis server port
    - REDIS_PASSWORD: Redis password (optional)
    - REDIS_DB: Redis database number
    - REDIS_PREFIX: Prefix for Redis keys
    - REDIS_USE_SSL: Whether to use SSL for connection
    - REDIS_SOCKET_TIMEOUT: Socket timeout in seconds
    - REDIS_CONNECTION_TIMEOUT: Connection timeout in seconds
    - REDIS_RETRY_ON_TIMEOUT: Whether to retry on timeout
    - REDIS_POOL_MIN_SIZE: Minimum connection pool size
    - REDIS_POOL_MAX_SIZE: Maximum connection pool size
    - REDIS_DEFAULT_TTL: Default TTL for cache items in seconds
    """

    PREFIX = "REDIS"

    # Connection settings
    host: str = Field(default="localhost", description="Redis server host")
    port: int = Field(default=6379, description="Redis server port")
    password: Optional[SecretStr] = Field(default=None, description="Redis password")
    db: int = Field(default=0, description="Redis database number")
    prefix: str = Field(default="ds_adh:", description="Prefix for Redis keys")

    # SSL settings
    use_ssl: bool = Field(default=False, description="Use SSL for connection")

    # Timeout settings
    socket_timeout: int = Field(default=5, description="Socket timeout in seconds")
    connection_timeout: int = Field(default=5, description="Connection timeout in seconds")
    retry_on_timeout: bool = Field(default=True, description="Retry on timeout")

    # Connection pool settings
    pool_min_size: int = Field(default=1, description="Minimum connection pool size")
    pool_max_size: int = Field(
        default=50,
        description="Maximum connections for cache/commands. Pub/Sub uses a separate pool.",
    )
    pubsub_pool_max_size: int = Field(
        default=64,
        description="Maximum Redis connections reserved for Buzz SSE and Hermes listeners",
    )

    # Cache settings
    default_ttl: int = Field(default=3600, description="Default TTL for cache items in seconds")

    @computed_field
    @property
    def connection_params(self) -> Dict:
        """Get Redis connection parameters."""
        params = {
            "host": self.host,
            "port": self.port,
            "db": self.db,
            "socket_timeout": self.socket_timeout,
            "socket_connect_timeout": self.connection_timeout,
            "retry_on_timeout": self.retry_on_timeout,
            "max_connections": self.pool_max_size,
        }

        if self.password:
            params["password"] = self.password.get_secret_value()

        if self.use_ssl:
            params["ssl"] = self.use_ssl

        return params
