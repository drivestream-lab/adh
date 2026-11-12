"""Per-(tenant, role, work_id) Redis work sessions for the Team OS control plane."""

from __future__ import annotations

from typing import Optional

from injector import inject

from src.adh_agents.runtime.work_models import UNBOUND_WORK_ID, AgentWorkSession
from src.adh_agents.settings import AgentSettings
from src.business_services.base_business_service import BaseBusinessService
from src.infra_services.redis_service import RedisService

_KEY_PREFIX = "adh:agent:work:"
_INDEX_PREFIX = "adh:agent:works:"


def _normalize_work_id(work_id: str) -> str:
    """INIT ids uppercased; ``__unbound__`` kept canonical (case-stable).

    Uppercasing the unbound sentinel made ``save`` treat ``__UNBOUND__ !=
    __unbound__`` and immediately delete the key it just wrote — resume picks
    never stuck.
    """
    raw = (work_id or UNBOUND_WORK_ID).strip() or UNBOUND_WORK_ID
    if raw.lower() == UNBOUND_WORK_ID.lower():
        return UNBOUND_WORK_ID
    return raw.upper()


def work_key(tenant: str, role_id: str, work_id: str) -> str:
    return f"{_KEY_PREFIX}{tenant}:{role_id}:{_normalize_work_id(work_id)}"


def works_index_key(tenant: str, role_id: str) -> str:
    return f"{_INDEX_PREFIX}{tenant}:{role_id}"


def _work_id_part(session: AgentWorkSession) -> str:
    init = session.initiative
    if init and init.strip():
        return init.strip().upper()
    return _normalize_work_id(session.work_id or UNBOUND_WORK_ID)


class AgentWorkStore(BaseBusinessService):
    """Load / save / clear role-scoped work sessions for a tenant."""

    @inject
    def __init__(self, redis: RedisService) -> None:
        super().__init__()
        self._redis = redis
        try:
            self._ttl = int(AgentSettings.get_instance().work_ttl_seconds)
        except Exception:
            self._ttl = 172800

    async def load(self, tenant: str, role_id: str, work_id: str) -> Optional[AgentWorkSession]:
        raw = await self._redis.get(work_key(tenant, role_id, work_id), as_json=True)
        if raw is None:
            return None
        return AgentWorkSession.model_validate(raw)

    async def load_unbound(self, tenant: str, role_id: str) -> Optional[AgentWorkSession]:
        return await self.load(tenant, role_id, UNBOUND_WORK_ID)

    async def list_active(self, tenant: str, role_id: str) -> list[AgentWorkSession]:
        ids = await self._index_members(tenant, role_id)
        sessions: list[AgentWorkSession] = []
        stale: list[str] = []
        for work_id in ids:
            session = await self.load(tenant, role_id, work_id)
            if session is None:
                stale.append(work_id)
                continue
            sessions.append(session)
        for work_id in stale:
            await self._index_remove(tenant, role_id, work_id)
        sessions.sort(key=lambda s: (s.work_id or "", s.updated_at.isoformat()))
        return sessions

    async def list_open_gates(self, tenant: str, role_id: str) -> list[AgentWorkSession]:
        return [
            s
            for s in await self.list_active(tenant, role_id)
            if s.awaiting in ("judgment", "authorization") and s.open_brief is not None
        ]

    async def has_active(self, tenant: str, role_id: str) -> bool:
        return bool(await self._index_members(tenant, role_id))

    async def save(self, session: AgentWorkSession) -> None:
        session.touch()
        wid = _work_id_part(session)
        session.work_id = wid
        if session.initiative:
            session.initiative = session.initiative.strip().upper()
        await self._redis.set(
            work_key(session.tenant_slug, session.role_id, wid),
            session.model_dump(mode="json"),
            ttl=self._ttl,
        )
        await self._index_add(session.tenant_slug, session.role_id, wid)
        if _normalize_work_id(wid) != UNBOUND_WORK_ID:
            await self._delete_key(session.tenant_slug, session.role_id, UNBOUND_WORK_ID)
        self.logger.info(
            "Saved agent work session",
            tenant=session.tenant_slug,
            role=session.role_id,
            work_id=wid,
            stage=session.stage,
            awaiting=session.awaiting,
            programme=session.programme,
        )

    async def clear(
        self,
        tenant: str,
        role_id: str,
        work_id: Optional[str] = None,
    ) -> None:
        if work_id is None:
            for wid in list(await self._index_members(tenant, role_id)):
                await self._delete_key(tenant, role_id, wid)
            await self._redis.delete(works_index_key(tenant, role_id))
            self.logger.info("Cleared all agent work sessions", tenant=tenant, role=role_id)
            return
        wid = _normalize_work_id(work_id)
        await self._delete_key(tenant, role_id, wid)
        self.logger.info("Cleared agent work session", tenant=tenant, role=role_id, work_id=wid)

    async def _delete_key(self, tenant: str, role_id: str, work_id: str) -> None:
        await self._redis.delete(work_key(tenant, role_id, work_id))
        await self._index_remove(tenant, role_id, work_id)

    async def _index_members(self, tenant: str, role_id: str) -> list[str]:
        raw = await self._redis.get(works_index_key(tenant, role_id), as_json=True)
        if raw is None:
            return []
        if isinstance(raw, list):
            return sorted({_normalize_work_id(str(x)) for x in raw if str(x).strip()})
        return []

    async def _index_add(self, tenant: str, role_id: str, work_id: str) -> None:
        members = set(await self._index_members(tenant, role_id))
        members.add(_normalize_work_id(work_id))
        await self._redis.set(
            works_index_key(tenant, role_id),
            sorted(members),
            ttl=self._ttl,
        )

    async def _index_remove(self, tenant: str, role_id: str, work_id: str) -> None:
        members = set(await self._index_members(tenant, role_id))
        members.discard(_normalize_work_id(work_id))
        key = works_index_key(tenant, role_id)
        if not members:
            await self._redis.delete(key)
            return
        await self._redis.set(key, sorted(members), ttl=self._ttl)
