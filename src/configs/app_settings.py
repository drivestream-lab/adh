"""Application-wide settings for adh."""

from enum import Enum
from typing import ClassVar

from pydantic import Field, field_validator

from src.configs.base_settings import BaseSettings


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGE = "stage"
    TESTING = "testing"
    PRODUCTION = "production"


class AppSettings(BaseSettings):
    """Application configuration settings."""

    PREFIX: ClassVar[str] = "APP"

    environment: Environment = Field(default=Environment.DEVELOPMENT)
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    api_prefix: str = Field(default="/api")
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="text", description="'json' in production, 'text' locally")
    log_to_console: bool = Field(default=True)
    log_dir: str = Field(default="logs")
    reload: bool = Field(
        default=False,
        description="Uvicorn --reload. Leave false in Docker so Buzz SSE stays connected.",
    )

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("text", "json"):
            raise ValueError("log_format must be 'text' or 'json'")
        return v_lower

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid:
            raise ValueError(f"Log level must be one of {valid}")
        return v_upper

    @property
    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT
