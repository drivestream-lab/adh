"""F7 — archive / delete / keep Lead tokens."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.adh_agents.collaboration.human_replies import (
    ARCHIVE_TASK,
    DELETE_TASK,
    KEEP_OPEN,
    normalize_reply,
)
from src.adh_agents.programmes.pm.task_lifecycle import TaskLifecycleProgramme
from src.models.buzz_models import TaskKind, TaskRead, TaskSource, TaskState
from src.models.tenant_models import TenantContext


def test_archive_aliases() -> None:
    allowed = [ARCHIVE_TASK, DELETE_TASK, KEEP_OPEN]
    assert normalize_reply("archive task", allowed) == ARCHIVE_TASK
    assert normalize_reply("archive", allowed) == ARCHIVE_TASK
    assert normalize_reply("delete task", allowed) == DELETE_TASK
    assert normalize_reply("keep open", allowed) == KEEP_OPEN


def test_handle_archive_token() -> None:
    buzz = MagicMock()
    buzz.archive_task = AsyncMock(
        return_value=TaskRead(
            id=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            tenant_slug="realworld",
            kind=TaskKind.INIT,
            task_id="INIT-REALWORLD-001",
            title="t",
            state=TaskState.ARCHIVED,
            source=TaskSource.BUZZ,
            hub_room_slug="realworld-ops",
            task_room_slug="task-init-realworld-001",
            archived_at=datetime.now(UTC),
            archived_by="nikd10x",
        )
    )
    poster = MagicMock()
    poster.post_status = AsyncMock()
    poster.ack_received = AsyncMock()
    life = TaskLifecycleProgramme(
        buzz=buzz,
        poster=poster,
        gates=MagicMock(),
        briefs=MagicMock(),
        store=MagicMock(),
    )
    tenant = TenantContext(
        slug="realworld",
        org="10xScale-AILabs",
        meta_repo="realworld-meta",
        meta_root="/tmp/realworld-meta",
    )

    async def _run() -> bool:
        return await life.handle_lead_token(
            tenant,
            "task-init-realworld-001",
            body="archive task",
            lead_handle="nikd10x",
        )

    assert asyncio.run(_run()) is True
    buzz.archive_task.assert_awaited()


def test_god_coach_archive_plays_recommend(monkeypatch) -> None:
    """God mode: coach_archive auto-plays ``archive task`` via GateOpener."""
    from src.adh_agents.settings import AdhAutonomySettings
    from src.configs.base_settings import BaseSettings

    monkeypatch.setenv("ADH_AUTONOMY_MODE", "god")
    BaseSettings._instances.pop(AdhAutonomySettings.__name__, None)

    buzz = MagicMock()
    buzz.set_task_state = AsyncMock()
    buzz.archive_task = AsyncMock(
        return_value=TaskRead(
            id=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            tenant_slug="realworld",
            kind=TaskKind.INIT,
            task_id="INIT-REALWORLD-004",
            title="t",
            state=TaskState.ARCHIVED,
            source=TaskSource.BUZZ,
            hub_room_slug="realworld-ops",
            task_room_slug="task-init-realworld-004",
            archived_at=datetime.now(UTC),
            archived_by="adh.system",
        )
    )
    poster = MagicMock()
    poster.post_status = AsyncMock()
    poster.ack_received = AsyncMock()
    gates = MagicMock()
    gates.open = AsyncMock(return_value=ARCHIVE_TASK)
    briefs = MagicMock()
    briefs.build_brief = MagicMock(return_value=MagicMock())
    store = MagicMock()
    store.clear = AsyncMock()
    life = TaskLifecycleProgramme(buzz=buzz, poster=poster, gates=gates, briefs=briefs, store=store)
    tenant = TenantContext(
        slug="realworld",
        org="10xScale-AILabs",
        meta_repo="realworld-meta",
        meta_root="/tmp/realworld-meta",
        ops_room="realworld-ops",
    )

    async def _run() -> None:
        await life.coach_archive(
            tenant,
            "task-init-realworld-004",
            task_id="INIT-REALWORLD-004",
            i_did="Finished knowledge enrich.",
            identity_handle="adh.kb",
        )

    asyncio.run(_run())
    gates.open.assert_awaited()
    buzz.archive_task.assert_awaited()
    store.clear.assert_awaited()
    BaseSettings._instances.pop(AdhAutonomySettings.__name__, None)
