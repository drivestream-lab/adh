"""F.4b — army collaboration targets task room, not hub."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.adh_agents.runtime.room_resolve import collaboration_room, task_room_slug_for
from src.models.buzz_models import TaskKind, TaskRead, TaskSource, TaskState
from src.models.tenant_models import TenantContext


def _tenant() -> TenantContext:
    return TenantContext(
        slug="realworld",
        org="10xScale-AILabs",
        meta_repo="realworld-meta",
        meta_root="/tmp/realworld-meta",
        init_prefix="INIT-REALWORLD-",
        ops_room="realworld-ops",
    )


def test_task_room_slug_for() -> None:
    assert task_room_slug_for("INIT-REALWORLD-003") == "task-init-realworld-003"


def test_collaboration_room_uses_pg_task() -> None:
    buzz = MagicMock()
    task = TaskRead(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        tenant_slug="realworld",
        kind=TaskKind.INIT,
        task_id="INIT-REALWORLD-003",
        title="Floor verify",
        state=TaskState.BOUND,
        source=TaskSource.BUZZ,
        source_ref="buzz:outline:INIT-REALWORLD-003",
        hub_room_slug="realworld-ops",
        task_room_slug="task-init-realworld-003",
    )
    buzz.get_task = AsyncMock(return_value=task)
    room = asyncio.run(
        collaboration_room(
            buzz, _tenant(), initiative="INIT-REALWORLD-003", fallback="realworld-ops"
        )
    )
    assert room == "task-init-realworld-003"
    buzz.get_task.assert_awaited_once()


def test_collaboration_room_deterministic_when_missing() -> None:
    buzz = MagicMock()
    buzz.get_task = AsyncMock(side_effect=LookupError("missing"))
    room = asyncio.run(
        collaboration_room(
            buzz, _tenant(), initiative="INIT-REALWORLD-003", fallback="realworld-ops"
        )
    )
    assert room == "task-init-realworld-003"
