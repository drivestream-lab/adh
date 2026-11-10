"""F9 — GitHub issue bind stub (unique source_ref)."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.adh_agents.ingress.github_ingress import GitHubIngressService
from src.models.buzz_models import (
    RoomMemberRead,
    TaskKind,
    TaskRead,
    TaskSource,
    TaskState,
)
from src.models.tenant_models import TenantContext


def test_kind_from_labels() -> None:
    svc = GitHubIngressService(MagicMock(), MagicMock(), MagicMock())
    assert svc.kind_from_labels(["bug"]) == TaskKind.BUG
    assert svc.kind_from_labels(["enhancement"]) == TaskKind.ENHANCEMENT
    assert svc.kind_from_labels(["docs"]) is None


def test_bind_issue_creates_task() -> None:
    buzz = MagicMock()
    buzz.list_members = AsyncMock(
        return_value=[
            RoomMemberRead(
                id=uuid4(),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                room_id=uuid4(),
                identity_id=uuid4(),
                identity_handle="adh.pm",
                identity_display_name="PM",
                member_role="participant",
            )
        ]
    )
    buzz.create_task = AsyncMock(
        return_value=TaskRead(
            id=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            tenant_slug="realworld",
            kind=TaskKind.BUG,
            task_id="BUG-REALWORLD-042",
            title="Broken login",
            state=TaskState.BOUND,
            source=TaskSource.GITHUB,
            source_ref="github:realworld-api#42",
            hub_room_slug="realworld-ops",
            task_room_slug="task-bug-realworld-042",
        )
    )
    buzz.ensure_member = AsyncMock()
    buzz.append_task_event = AsyncMock()
    poster = MagicMock()
    poster.post_status = AsyncMock()
    tenants = MagicMock()
    tenants.by_slug.return_value = TenantContext(
        slug="realworld",
        org="10xScale-AILabs",
        meta_repo="realworld-meta",
        meta_root="/tmp/realworld-meta",
    )
    svc = GitHubIngressService(buzz, poster, tenants)

    async def _run():
        return await svc.bind_issue(
            tenant_slug="realworld",
            repo="realworld-api",
            issue_number=42,
            title="Broken login",
            labels=["bug"],
            issue_url="https://github.com/org/realworld-api/issues/42",
        )

    task = asyncio.run(_run())
    assert task is not None
    assert task.task_id == "BUG-REALWORLD-042"
    create = buzz.create_task.await_args.args[0]
    assert create.source_ref == "github:realworld-api#42"


def test_bind_stalls_without_hired_role() -> None:
    buzz = MagicMock()
    buzz.list_members = AsyncMock(return_value=[])
    poster = MagicMock()
    poster.post_status = AsyncMock()
    tenants = MagicMock()
    tenants.by_slug.return_value = TenantContext(
        slug="realworld",
        org="10xScale-AILabs",
        meta_repo="realworld-meta",
        meta_root="/tmp/realworld-meta",
    )
    svc = GitHubIngressService(buzz, poster, tenants)

    async def _run():
        return await svc.bind_issue(
            tenant_slug="realworld",
            repo="realworld-api",
            issue_number=7,
            title="x",
            labels=["bug"],
        )

    assert asyncio.run(_run()) is None
    poster.post_status.assert_awaited()
    buzz.create_task.assert_not_called()
