"""F4 — Redis presence keys (never chat)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.adh_agents.runtime.presence import PresenceService


def test_presence_heartbeat_sets_ttl() -> None:
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=b"listening")
    svc = PresenceService(redis)

    async def _run() -> None:
        await svc.heartbeat(tenant="realworld", role_id="adh.pm", ttl_seconds=120)
        state = await svc.get(tenant="realworld", role_id="adh.pm")
        assert state == "listening"

    asyncio.run(_run())
    redis.set.assert_awaited()
    key = redis.set.await_args.args[0]
    assert key.startswith("adh:presence:realworld:adh.pm")
    assert redis.set.await_args.kwargs.get("ttl") == 120
