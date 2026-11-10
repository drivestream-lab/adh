"""F5 — CollabPost helper on HermesBuzzPoster."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.models.buzz_models import EventType, MessageKind, MessageRead


def test_post_collab_mentions_and_flags() -> None:
    buzz = MagicMock()
    buzz.post_message = AsyncMock(
        return_value=MessageRead(
            id=uuid4(),
            room_id=uuid4(),
            identity_id=uuid4(),
            identity_handle="adh.pe",
            identity_display_name="PE",
            body="@adh.pm claimed",
            kind=MessageKind.EVENT,
            event_type=EventType.START,
            payload={"collab": True, "status": "pe_claimed"},
        )
    )
    poster = HermesBuzzPoster(buzz, MagicMock())

    async def _run() -> None:
        msg = await poster.post_collab(
            "task-init-1",
            body="claimed",
            identity_handle="adh.pe",
            status="pe_claimed",
            mention="adh.pm",
        )
        assert msg.payload and msg.payload.get("collab") is True

    asyncio.run(_run())
    create = buzz.post_message.await_args.args[1]
    assert "@adh.pm" in create.body
    assert create.payload.get("collab") is True
    assert create.payload.get("status") == "pe_claimed"
