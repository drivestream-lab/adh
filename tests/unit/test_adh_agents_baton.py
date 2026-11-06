"""Unit tests for Redis baton store + forge ACL."""

from __future__ import annotations

import asyncio
from typing import Any, Optional


from src.adh_agents.baton.models import Baton, BatonStatus
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.forge_acl import forge_allowed


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def set_if_absent(self, key: str, value: Any, ttl: int) -> bool:
        if key in self._data:
            return False
        self._data[key] = value if isinstance(value, str) else str(value)
        return True

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        self._data[key] = value if isinstance(value, str) else str(value)
        return True

    async def get(self, key: str, as_json: bool = False) -> Any:
        return self._data.get(key)


def test_forge_acl_default_deny() -> None:
    assert forge_allowed("adh.pm", "open_draft_pr")
    assert forge_allowed("adh.pm", "prd_merge")
    assert not forge_allowed("adh.pm", "approve_attestation")
    assert not forge_allowed("adh.read", "open_draft_pr")
    assert forge_allowed("adh.pe", "approve_attestation")


def test_baton_create_claim_done() -> None:
    store = RedisBatonStore.__new__(RedisBatonStore)
    store._redis = _FakeRedis()  # type: ignore[assignment]
    store._prefix = "adh:baton"

    baton = Baton(
        type="pe.review",
        from_role="adh.pm",
        to_role="adh.pe",
        tenant="realworld",
        ops_room="realworld-ops",
        initiative="INIT-TEST",
        idempotency_key="pe.review:realworld:INIT-TEST:draft",
    )

    created, is_new = asyncio.run(store.create_pending(baton, ttl=60))
    assert is_new
    assert created.status == BatonStatus.PENDING

    again, is_new2 = asyncio.run(store.create_pending(baton, ttl=60))
    assert not is_new2
    assert again.id == created.id

    assert asyncio.run(store.claim(created, claimant="adh.pe", ttl=60))
    loaded = asyncio.run(
        store.get(tenant="realworld", idempotency_key="pe.review:realworld:INIT-TEST:draft")
    )
    assert loaded is not None
    assert loaded.status == BatonStatus.CLAIMED
    assert loaded.claimed_by == "adh.pe"

    done = asyncio.run(store.mark_done(loaded, ttl=60))
    assert done.status == BatonStatus.DONE
