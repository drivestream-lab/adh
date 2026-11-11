"""Lead traj detailed card posts on ops room."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adh_agents.programmes.pm.traj_coach import TrajCoachProgramme


@pytest.mark.asyncio
async def test_traj_card_posts_to_ops_not_task_room() -> None:
    buzz = MagicMock()
    buzz.list_task_events = AsyncMock(return_value=[])
    poster = MagicMock()
    poster.ack_received = AsyncMock()
    poster.post_status = AsyncMock()

    coach = TrajCoachProgramme(buzz=buzz, poster=poster)
    tenant = MagicMock()
    tenant.slug = "realworld"
    tenant.ops_room = "realworld-ops"
    tenant.init_prefix = "INIT-REALWORLD-"

    ok = await coach.handle_lead(
        tenant,
        "task-init-realworld-001",
        body="traj",
        task_id="INIT-REALWORLD-001",
    )
    assert ok is True
    # Detailed card on ops
    first_card = [
        c for c in poster.post_status.await_args_list if c.args and c.args[0] == "realworld-ops"
    ]
    assert first_card
    # Pointer in task room
    pointer = [
        c
        for c in poster.post_status.await_args_list
        if c.args and c.args[0] == "task-init-realworld-001"
    ]
    assert pointer
