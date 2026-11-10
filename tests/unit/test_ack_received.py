"""Base premise: Lead ingest ack before long work."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.adh_agents.surface.buzz_poster import HermesBuzzPoster, _lead_snippet
from src.models.buzz_models import EventType


def test_lead_snippet_trims_and_ellipsizes() -> None:
    assert _lead_snippet("  go   ahead  ") == "go ahead"
    long = "x" * 100
    out = _lead_snippet(long, limit=20)
    assert out.endswith("…")
    assert len(out) == 20


def test_ack_received_posts_start_event() -> None:
    buzz = MagicMock()
    buzz.post_message = AsyncMock(return_value=MagicMock())
    poster = HermesBuzzPoster(buzz=buzz, prompts=MagicMock())

    asyncio.run(
        poster.ack_received(
            "task-init-realworld-003",
            lead_body="go ahead",
            identity_handle="adh.kb",
            source_message_id="msg-1",
        )
    )

    buzz.post_message.assert_awaited_once()
    room, create = buzz.post_message.await_args.args
    assert room == "task-init-realworld-003"
    assert create.identity_handle == "adh.kb"
    assert create.event_type == EventType.START
    assert create.payload["status"] == "received"
    assert create.payload["ack"] is True
    assert "go ahead" in create.body
    assert create.body.startswith("Got it — working on")
