"""PostgreSQL settings for adh."""

from typing import ClassVar, Dict, Optional
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, computed_field

from src.configs.base_settings import BaseSettings


class PostgresSettings(BaseSettings):
    """Settings for PostgreSQL database connection."""

    PREFIX: ClassVar[str] = "POSTGRES"

    host: str = Field(default="localhost", description="PostgreSQL host")
    port: int = Field(default=5432, description="PostgreSQL port")
    user: str = Field(default="adh", description="PostgreSQL user")
    password: SecretStr = Field(default=SecretStr("adh"), description="PostgreSQL password")
    db: str = Field(
        default="buzz",
        description="PostgreSQL database name",
    )
    min_pool_size: int = Field(default=5, description="Minimum connection pool size")
    max_pool_size: int = Field(default=20, description="Maximum connection pool size")
    pool_timeout: int = Field(default=30, description="Pool timeout in seconds")
    pool_recycle: int = Field(default=1800, description="Pool recycle interval in seconds")
    use_ssl: bool = Field(default=False, description="Use SSL for connection")
    ssl_mode: Optional[str] = Field(default=None, description="SSL mode")
    connect_timeout: int = Field(default=10, description="Connection timeout in seconds")
    command_timeout: int = Field(default=30, description="Command timeout in seconds")

    @computed_field
    @property
    def sqlalchemy_database_uri(self) -> str:
        password = quote_plus(self.password.get_secret_value())
        return f"postgresql+asyncpg://{self.user}:{password}@{self.host}:{self.port}/{self.db}"

    @computed_field
    @property
    def alembic_database_uri(self) -> str:
        password = quote_plus(self.password.get_secret_value())
        conn_str = f"postgresql+psycopg2://{self.user}:{password}@{self.host}:{self.port}/{self.db}"
        if self.use_ssl:
            conn_str += f"?sslmode={'require' if not self.ssl_mode else self.ssl_mode}"
        return conn_str

    @computed_field
    @property
    def sqlalchemy_engine_args(self) -> Dict:
        connect_args = {
            "timeout": self.connect_timeout,
            "command_timeout": self.command_timeout,
            "server_settings": {"application_name": "adh"},
        }
        if self.use_ssl:
            connect_args["ssl"] = "require" if not self.ssl_mode else self.ssl_mode
        return {
            "pool_pre_ping": True,
            "pool_size": self.min_pool_size,
            "max_overflow": self.max_pool_size - self.min_pool_size,
            "pool_timeout": self.pool_timeout,
            "pool_recycle": self.pool_recycle,
            "connect_args": connect_args,
        }
