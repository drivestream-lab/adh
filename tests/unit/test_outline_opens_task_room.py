"""F6 — outline bind creates PG task + task room."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.adh_agents.programmes.pm.authoring import AuthoringProgrammeService
from src.models.buzz_models import TaskKind, TaskRead, TaskSource, TaskState
from src.models.tenant_models import TenantContext
from datetime import UTC, datetime
from uuid import uuid4


def test_open_task_room_creates_and_announces() -> None:
    store = MagicMock()
    store.save = AsyncMock()
    buzz = MagicMock()
    task = TaskRead(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        tenant_slug="realworld",
        kind=TaskKind.INIT,
        task_id="INIT-REALWORLD-009",
        title="Ship floor",
        state=TaskState.BOUND,
        source=TaskSource.BUZZ,
        source_ref="buzz:outline:INIT-REALWORLD-009",
        hub_room_slug="realworld-ops",
        task_room_slug="task-init-realworld-009",
    )
    buzz.create_task = AsyncMock(return_value=task)
    buzz.ensure_member = AsyncMock()
    poster = MagicMock()
    poster.post_status = AsyncMock()
    svc = AuthoringProgrammeService(
        store=store,
        dispatch=MagicMock(),
        briefs=MagicMock(),
        poster=poster,
        workspace=MagicMock(),
        buzz=buzz,
        gates=MagicMock(),
        autonomy=MagicMock(),
        meta_pm=MagicMock(),
    )
    tenant = TenantContext(
        slug="realworld",
        org="10xScale-AILabs",
        meta_repo="realworld-meta",
        meta_root="/tmp/realworld-meta",
        init_prefix="INIT-REALWORLD-",
    )

    async def _run() -> str:
        return await svc._open_task_room(
            tenant,
            hub_room="realworld-ops",
            initiative="INIT-REALWORLD-009",
            outline="Ship floor wave",
        )

    room = asyncio.run(_run())
    assert room == "task-init-realworld-009"
    buzz.create_task.assert_awaited()
    poster.post_status.assert_awaited()
    assert buzz.ensure_member.await_count >= 1
