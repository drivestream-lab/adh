"""PE programme claims pe.review and emits read.walk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from src.adh_agents.baton.models import Baton, BatonStatus
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.pe.review import PeReviewProgramme
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str, as_json: bool = False) -> Any:
        raw = self.data.get(key)
        if raw is not None and as_json:
            return json.loads(raw)
        return raw

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        self.data[key] = value if isinstance(value, str) else json.dumps(value)
        return True

    async def set_if_absent(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        if key in self.data:
            return False
        await self.set(key, value, ttl=ttl)
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.data.pop(key, None) is not None else 0


class _FakePoster:
    def __init__(self) -> None:
        self.posts: list[str] = []

    async def post_status(
        self,
        room: str,
        body: str,
        event_type: EventType = EventType.PROGRESS,
        payload: Optional[dict[str, Any]] = None,
        identity_handle: Optional[str] = None,
    ) -> None:
        self.posts.append(body)

    async def post_collab(
        self,
        room: str,
        *,
        body: str,
        identity_handle: str,
        status: str,
        payload: Optional[dict[str, Any]] = None,
        event_type: EventType = EventType.PROGRESS,
        mention: str = "",
    ) -> None:
        del room, identity_handle, status, payload, event_type
        text = body
        if mention and f"@{mention}" not in text:
            text = f"@{mention} {text}"
        self.posts.append(text)


@pytest.mark.asyncio
async def test_pe_claims_and_emits_read_walk(tmp_path: Path) -> None:
    redis = _FakeRedis()
    batons = RedisBatonStore(redis)  # type: ignore[arg-type]
    store = AgentWorkStore(redis)  # type: ignore[arg-type]
    reports = tmp_path / "prd" / "reports"
    reports.mkdir(parents=True)

    tenant = TenantContext(
        slug="realworld",
        org="org",
        ops_room="realworld-ops",
        meta_repo="org/meta",
        meta_root=str(tmp_path),
        init_prefix="INIT-REALWORLD",
    )
    tenants = MagicMock()
    tenants.by_slug.return_value = tenant
    workspace = MagicMock()
    workspace.purge_local_paths.return_value = []
    forge = MagicMock()
    briefs = MagicMock()

    buzz = MagicMock()

    async def _no_task(*_a: Any, **_k: Any) -> None:
        raise LookupError("no task in unit test")

    buzz.get_task = _no_task
    pe = PeReviewProgramme(
        store=store,
        batons=batons,
        poster=_FakePoster(),  # type: ignore[arg-type]
        briefs=briefs,
        forge=forge,
        workspace=workspace,
        tenants=tenants,
        buzz=buzz,  # type: ignore[arg-type]
        engg_handoff=MagicMock(),
    )
    baton = Baton(
        type="pe.review",
        from_role="adh.pm",
        to_role="adh.pe",
        tenant="realworld",
        ops_room="realworld-ops",
        initiative="INIT-REALWORLD-001",
        idempotency_key="pe.review:realworld:INIT-REALWORLD-001:draft",
        payload={"pr_url": "https://example/pr/1"},
    )
    await batons.create_pending(baton, ttl=60)
    rollup = await pe.handle_baton(baton, room="realworld-ops")
    assert rollup.status == BatonStatus.DONE
    walk = await batons.get(
        tenant="realworld",
        idempotency_key="read.walk:realworld:INIT-REALWORLD-001:org/meta",
    )
    assert walk is not None
    assert walk.type == "read.walk"
    live = await store.load("realworld", "adh.pe", "INIT-REALWORLD-001")
    assert live is not None
    assert live.programme == "pe"
    assert live.stage == "gate1_await_pm"
    brief = tmp_path / "prd" / "reports" / "INIT-REALWORLD-001-hermes-gate1-brief.md"
    assert brief.is_file()
    text = brief.read_text(encoding="utf-8")
    assert "**Buying.**" in text
    assert "recommend: await_pm" in text
