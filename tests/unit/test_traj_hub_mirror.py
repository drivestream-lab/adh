"""T1 — trajectory append mirrors a Buzz-light line onto tenant ops."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.business_services.buzz_service import BuzzService
from src.database.postgres.schema.buzz_schema import BuzzTaskSchema
from src.models.buzz_models import (
    EventType,
    MessageKind,
    TaskEventCreate,
    TaskEventKind,
    TaskEventRead,
)
from datetime import UTC, datetime
from uuid import uuid4


def test_append_task_event_mirrors_to_hub() -> None:
    buzz = object.__new__(BuzzService)
    buzz.logger = MagicMock()
    session = MagicMock()
    event = TaskEventRead(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        tenant_slug="realworld",
        task_id="INIT-REALWORLD-003",
        seq=1,
        kind=TaskEventKind.GATE_OPEN,
        role_id="adh.kb",
        purpose="kb-enrich",
        token="",
        evidence_ref="",
        payload=None,
    )
    task = BuzzTaskSchema(
        id=uuid4(),
        tenant_slug="realworld",
        kind="init",
        task_id="INIT-REALWORLD-003",
        title="demo",
        state="gated",
        source="buzz",
        source_ref="buzz:outline:INIT-REALWORLD-003",
        hub_room_slug="realworld-ops",
        task_room_slug="task-init-realworld-003",
    )

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    buzz._postgres = MagicMock()
    buzz._postgres.get_session = MagicMock(return_value=cm)
    buzz._append_event_unlocked = AsyncMock(return_value=event)
    buzz._get_task = AsyncMock(return_value=task)
    buzz._mirror_traj_to_hub = AsyncMock()

    out = asyncio.run(
        BuzzService.append_task_event(
            buzz,
            TaskEventCreate(
                tenant_slug="realworld",
                task_id="INIT-REALWORLD-003",
                kind=TaskEventKind.GATE_OPEN,
                role_id="adh.kb",
                purpose="kb-enrich",
            ),
        )
    )
    assert out.seq == 1
    buzz._mirror_traj_to_hub.assert_awaited_once()


def test_mirror_traj_posts_hub_event() -> None:
    buzz = object.__new__(BuzzService)
    buzz.logger = MagicMock()
    session = MagicMock()
    task = BuzzTaskSchema(
        id=uuid4(),
        tenant_slug="realworld",
        kind="init",
        task_id="INIT-REALWORLD-003",
        title="demo",
        state="gated",
        source="buzz",
        source_ref="x",
        hub_room_slug="realworld-ops",
        task_room_slug="task-init-realworld-003",
    )
    event = TaskEventRead(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        tenant_slug="realworld",
        task_id="INIT-REALWORLD-003",
        seq=3,
        kind=TaskEventKind.GOD_TAKEN,
        role_id="adh.pm",
        purpose="prd-merge",
        token="go ahead",
        evidence_ref="",
        payload=None,
    )
    buzz._post_message = AsyncMock()
    asyncio.run(BuzzService._mirror_traj_to_hub(buzz, session, task, event))
    buzz._post_message.assert_awaited_once()
    await_args = buzz._post_message.await_args
    assert await_args is not None
    _session, room, create = await_args.args
    assert room == "realworld-ops"
    assert create.kind == MessageKind.EVENT
    assert create.event_type == EventType.PROGRESS
    assert create.payload["traj_mirror"] is True
    assert "traj `god_taken`" in create.body
    assert "#task-init-realworld-003" in create.body
