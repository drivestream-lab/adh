"""Role-scoped Buzz listen — engg floor is Dev-only."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adh_agents.runtime.room_resolve import listen_rooms_for_role


@pytest.mark.asyncio
async def test_dev_listens_hub_and_engg_not_task() -> None:
    buzz = MagicMock()
    buzz.list_active_task_rooms = AsyncMock(return_value=["task-init-realworld-002"])
    buzz.list_active_engg_rooms = AsyncMock(return_value=["engg-init-realworld-002"])
    tenant = MagicMock()
    tenant.ops_room = "realworld-ops"
    tenant.slug = "realworld"
    tenants = MagicMock()
    tenants.active = MagicMock(return_value=[tenant])

    rooms = await listen_rooms_for_role(buzz, tenants, "adh.dev")
    assert "realworld-ops" in rooms
    assert "engg-init-realworld-002" in rooms
    assert "task-init-realworld-002" not in rooms
    buzz.list_active_engg_rooms.assert_awaited()
    buzz.list_active_task_rooms.assert_not_awaited()


@pytest.mark.asyncio
async def test_pm_listens_hub_and_task_not_engg() -> None:
    buzz = MagicMock()
    buzz.list_active_task_rooms = AsyncMock(return_value=["task-init-realworld-002"])
    buzz.list_active_engg_rooms = AsyncMock(return_value=["engg-init-realworld-002"])
    tenant = MagicMock()
    tenant.ops_room = "realworld-ops"
    tenant.slug = "realworld"
    tenants = MagicMock()
    tenants.active = MagicMock(return_value=[tenant])

    rooms = await listen_rooms_for_role(buzz, tenants, "adh.pm")
    assert "realworld-ops" in rooms
    assert "task-init-realworld-002" in rooms
    assert "engg-init-realworld-002" not in rooms
    buzz.list_active_task_rooms.assert_awaited()
    buzz.list_active_engg_rooms.assert_not_awaited()
