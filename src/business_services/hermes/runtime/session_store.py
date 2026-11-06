"""Hermes session persistence — one Redis document per (tenant, initiative)."""

from __future__ import annotations

from typing import Optional

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.configs.hermes_settings import HermesSettings
from src.infra_services.redis_service import RedisService
from src.models.hermes.session_models import HermesSession

_KEY_PREFIX = "adh:hermes:session:"
_INDEX_PREFIX = "adh:hermes:sessions:"
# Clarify / resume-pick before an INIT is bound.
UNBOUND_INITIATIVE = "__unbound__"


def session_key(slug: str, initiative: str) -> str:
    init = (initiative or UNBOUND_INITIATIVE).strip().upper() or UNBOUND_INITIATIVE
    return f"{_KEY_PREFIX}{slug}:{init}"


def sessions_index_key(slug: str) -> str:
    return f"{_INDEX_PREFIX}{slug}"


def _initiative_key_part(session: HermesSession) -> str:
    init = (session.initiative or "").strip().upper()
    return init or UNBOUND_INITIATIVE


class HermesSessionStoreService(BaseBusinessService):
    """Load / save / clear initiative-scoped Hermes sessions for a tenant."""

    @inject
    def __init__(self, redis: RedisService) -> None:
        super().__init__()
        self._redis = redis
        self._ttl = HermesSettings.get_instance().session_ttl_seconds

    async def load(self, slug: str, initiative: str) -> Optional[HermesSession]:
        raw = await self._redis.get(session_key(slug, initiative), as_json=True)
        if raw is None:
            return None
        return HermesSession.model_validate(raw)

    async def load_unbound(self, slug: str) -> Optional[HermesSession]:
        return await self.load(slug, UNBOUND_INITIATIVE)

    async def list_active(self, slug: str) -> list[HermesSession]:
        """All sessions still present for the tenant (index + key reads)."""
        ids = await self._index_members(slug)
        sessions: list[HermesSession] = []
        stale: list[str] = []
        for initiative in ids:
            session = await self.load(slug, initiative)
            if session is None:
                stale.append(initiative)
                continue
            sessions.append(session)
        for initiative in stale:
            await self._index_remove(slug, initiative)
        sessions.sort(key=lambda s: (s.initiative or "", s.updated_at.isoformat()))
        return sessions

    async def list_open_gates(self, slug: str) -> list[HermesSession]:
        """Sessions waiting on judgment or authorization."""
        return [
            s
            for s in await self.list_active(slug)
            if s.awaiting in ("judgment", "authorization") and s.open_brief is not None
        ]

    async def has_active(self, slug: str) -> bool:
        return bool(await self._index_members(slug))

    async def save(self, session: HermesSession) -> None:
        session.touch()
        init = _initiative_key_part(session)
        if session.initiative:
            session.initiative = session.initiative.strip().upper()
        await self._redis.set(
            session_key(session.tenant_slug, init),
            session.model_dump(mode="json"),
            ttl=self._ttl,
        )
        await self._index_add(session.tenant_slug, init)
        # Binding an INIT retires the unbound clarify document.
        if init != UNBOUND_INITIATIVE:
            await self._delete_key(session.tenant_slug, UNBOUND_INITIATIVE)
        self.logger.info(
            "Saved Hermes session",
            slug=session.tenant_slug,
            initiative=init,
            stage=session.stage,
            awaiting=session.awaiting,
            programme=str(session.programme) if session.programme else None,
        )

    async def clear(self, slug: str, initiative: Optional[str] = None) -> None:
        """Clear one initiative session, or all sessions for the tenant when initiative is None."""
        if initiative is None:
            for init in list(await self._index_members(slug)):
                await self._delete_key(slug, init)
            await self._redis.delete(sessions_index_key(slug))
            # Legacy tenant-singleton key from pre-parallel store.
            await self._redis.delete(f"{_KEY_PREFIX}{slug}")
            self.logger.info("Cleared all Hermes sessions", slug=slug)
            return
        init = initiative.strip().upper() or UNBOUND_INITIATIVE
        await self._delete_key(slug, init)
        self.logger.info("Cleared Hermes session", slug=slug, initiative=init)

    async def _delete_key(self, slug: str, initiative: str) -> None:
        await self._redis.delete(session_key(slug, initiative))
        await self._index_remove(slug, initiative)

    async def _index_members(self, slug: str) -> list[str]:
        raw = await self._redis.get(sessions_index_key(slug), as_json=True)
        if raw is None:
            return []
        if isinstance(raw, list):
            return sorted({str(x).strip().upper() for x in raw if str(x).strip()})
        return []

    async def _index_add(self, slug: str, initiative: str) -> None:
        members = set(await self._index_members(slug))
        members.add(initiative.strip().upper() or UNBOUND_INITIATIVE)
        await self._redis.set(
            sessions_index_key(slug),
            sorted(members),
            ttl=self._ttl,
        )

    async def _index_remove(self, slug: str, initiative: str) -> None:
        members = set(await self._index_members(slug))
        members.discard(initiative.strip().upper() or UNBOUND_INITIATIVE)
        key = sessions_index_key(slug)
        if not members:
            await self._redis.delete(key)
            return
        await self._redis.set(key, sorted(members), ttl=self._ttl)
