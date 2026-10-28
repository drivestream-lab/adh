"""Shared fixtures for unit tests."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app import create_app
from src.configs.base_settings import BaseSettings
from src.di.dependency_container import configure_container, reset_container


@pytest.fixture(autouse=True)
def reset_settings() -> None:
    """Clear settings singletons and set minimal JWT env for in-process tests."""
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-ci-only")
    os.environ.setdefault("JWT_ALGORITHM", "HS256")
    for name in (
        "AppSettings",
        "JWTSettings",
        "PostgresSettings",
        "RedisSettings",
        "TelemetrySettings",
    ):
        BaseSettings._instances.pop(name, None)


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_postgres_service(mock_session: AsyncMock) -> MagicMock:
    @asynccontextmanager
    async def session_ctx() -> AsyncIterator[AsyncMock]:
        yield mock_session

    postgres = MagicMock()
    postgres.get_session = session_ctx
    postgres.transaction = session_ctx
    postgres.health_check = AsyncMock(return_value=True)
    postgres.get_session_factory = MagicMock(return_value=session_ctx)
    return postgres


@pytest.fixture
def mock_redis_service() -> MagicMock:
    redis = MagicMock()
    redis.health_check = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def client(
    mock_postgres_service: MagicMock,
    mock_redis_service: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    reset_container()
    configure_container()
    monkeypatch.setattr(
        "src.api.dependencies.get_postgres_service",
        lambda: mock_postgres_service,
    )
    monkeypatch.setattr(
        "src.api.dependencies.get_redis_service",
        lambda: mock_redis_service,
    )
    return TestClient(create_app(), raise_server_exceptions=False)
