"""F3 — durable Buzz tasks / archive / unique source_ref (service mocked)."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_buzz_service
from src.models.buzz_models import TaskKind, TaskRead, TaskSource, TaskState


def _override(client: TestClient, buzz: MagicMock) -> None:
    cast(FastAPI, client.app).dependency_overrides[get_buzz_service] = lambda: buzz


def _task(**kwargs) -> TaskRead:
    base = dict(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        tenant_slug="realworld",
        kind=TaskKind.INIT,
        task_id="INIT-REALWORLD-001",
        title="demo",
        state=TaskState.BOUND,
        source=TaskSource.BUZZ,
        source_ref="buzz:outline:INIT-REALWORLD-001",
        hub_room_slug="realworld-ops",
        task_room_slug="task-init-realworld-001",
        archived_at=None,
        archived_by=None,
    )
    base.update(kwargs)
    return TaskRead.model_validate(base)


def test_create_task_route(client: TestClient) -> None:
    buzz = MagicMock()
    buzz.create_task = AsyncMock(return_value=_task())
    _override(client, buzz)
    response = client.post(
        "/api/v1/buzz/tasks",
        json={
            "tenant_slug": "realworld",
            "kind": "init",
            "task_id": "INIT-REALWORLD-001",
            "title": "demo",
            "hub_room_slug": "realworld-ops",
            "source_ref": "buzz:outline:INIT-REALWORLD-001",
        },
    )
    assert response.status_code == 201
    assert response.json()["task_room_slug"] == "task-init-realworld-001"


def test_list_tasks_hides_archived_by_default(client: TestClient) -> None:
    buzz = MagicMock()
    buzz.list_tasks = AsyncMock(return_value=[_task()])
    _override(client, buzz)
    response = client.get("/api/v1/buzz/tenants/realworld/tasks")
    assert response.status_code == 200
    assert len(response.json()) == 1
    buzz.list_tasks.assert_awaited_with("realworld", include_archived=False)


def test_archive_task_route(client: TestClient) -> None:
    buzz = MagicMock()
    archived = _task(
        state=TaskState.ARCHIVED,
        archived_at=datetime.now(UTC),
        archived_by="nikd10x",
    )
    buzz.archive_task = AsyncMock(return_value=archived)
    _override(client, buzz)
    response = client.post(
        "/api/v1/buzz/tenants/realworld/tasks/INIT-REALWORLD-001/archive" "?archived_by=nikd10x"
    )
    assert response.status_code == 200
    assert response.json()["state"] == "archived"
