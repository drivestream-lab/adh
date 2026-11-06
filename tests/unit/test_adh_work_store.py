"""Agent work store — parallel (tenant, role, work_id) sessions."""

from __future__ import annotations

import json
from typing import Any, Optional

import pytest

from src.adh_agents.runtime.work_models import (
    AWAITING_JUDGMENT,
    UNBOUND_WORK_ID,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore, work_key, works_index_key


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, Optional[int]] = {}

    async def get(self, key: str, as_json: bool = False) -> Any:
        raw = self.data.get(key)
        if raw is not None and as_json:
            return json.loads(raw)
        return raw

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        self.data[key] = value if isinstance(value, str) else json.dumps(value)
        self.ttls[key] = ttl
        return True

    async def delete(self, key: str) -> int:
        self.ttls.pop(key, None)
        return 1 if self.data.pop(key, None) is not None else 0


@pytest.mark.asyncio
async def test_parallel_work_units_same_tenant_role() -> None:
    redis = _FakeRedis()
    store = AgentWorkStore(redis)  # type: ignore[arg-type]
    a = AgentWorkSession(
        tenant_slug="realworld",
        role_id="adh.pm",
        room="realworld-ops",
        work_id="INIT-A",
        initiative="INIT-A",
        stage="validate-requirements",
    )
    b = AgentWorkSession(
        tenant_slug="realworld",
        role_id="adh.pm",
        room="realworld-ops",
        work_id="INIT-B",
        initiative="INIT-B",
        stage="prd-impact-acceptance",
        awaiting=AWAITING_JUDGMENT,
    )
    await store.save(a)
    await store.save(b)
    active = await store.list_active("realworld", "adh.pm")
    assert {s.initiative for s in active} == {"INIT-A", "INIT-B"}
    assert work_key("realworld", "adh.pm", "INIT-A") in redis.data
    assert works_index_key("realworld", "adh.pm") in redis.data


@pytest.mark.asyncio
async def test_role_isolation() -> None:
    redis = _FakeRedis()
    store = AgentWorkStore(redis)  # type: ignore[arg-type]
    await store.save(
        AgentWorkSession(
            tenant_slug="realworld",
            role_id="adh.pm",
            room="realworld-ops",
            work_id="INIT-A",
            initiative="INIT-A",
        )
    )
    await store.save(
        AgentWorkSession(
            tenant_slug="realworld",
            role_id="adh.pe",
            room="realworld-ops",
            work_id="INIT-A",
            initiative="INIT-A",
            stage="gate1",
        )
    )
    pm = await store.list_active("realworld", "adh.pm")
    pe = await store.list_active("realworld", "adh.pe")
    assert len(pm) == 1 and pm[0].role_id == "adh.pm"
    assert len(pe) == 1 and pe[0].role_id == "adh.pe"


@pytest.mark.asyncio
async def test_clear_one_and_unbound() -> None:
    redis = _FakeRedis()
    store = AgentWorkStore(redis)  # type: ignore[arg-type]
    await store.save(
        AgentWorkSession(
            tenant_slug="t",
            role_id="adh.pm",
            room="ops",
            awaiting="clarify",
            work_id=UNBOUND_WORK_ID,
        )
    )
    await store.save(
        AgentWorkSession(
            tenant_slug="t",
            role_id="adh.pm",
            room="ops",
            work_id="INIT-1",
            initiative="INIT-1",
        )
    )
    await store.clear("t", "adh.pm", "INIT-1")
    assert await store.load("t", "adh.pm", "INIT-1") is None
    # unbound may have been cleared when INIT was saved
    await store.clear("t", "adh.pm")
    assert await store.list_active("t", "adh.pm") == []
