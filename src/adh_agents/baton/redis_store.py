"""Redis claim/running/done/expire for batons."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus
from src.infra_services.redis_service import RedisService
from src.logging import get_logger

logger = get_logger()

_DEFAULT_PREFIX = "adh:baton"


class RedisBatonStore:
    """Idempotent baton store. Claim is SET NX on the idempotency key."""

    @inject
    def __init__(self, redis: RedisService) -> None:
        self._redis = redis
        self._prefix = _DEFAULT_PREFIX

    def _key(self, baton: Baton) -> str:
        return baton.redis_key(prefix=self._prefix)

    async def put(self, baton: Baton, *, ttl: int) -> Baton:
        """Write baton JSON (overwrite). Used after create / status transitions."""
        baton.updated_at = datetime.now(timezone.utc)
        await self._redis.set(self._key(baton), baton.model_dump_json(), ttl=ttl)
        return baton

    async def get(self, *, tenant: str, idempotency_key: str) -> Optional[Baton]:
        raw = await self._redis.get(f"{self._prefix}:{tenant}:{idempotency_key}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return Baton.model_validate_json(raw)

    async def create_pending(self, baton: Baton, *, ttl: int) -> tuple[Baton, bool]:
        """Create if absent. Returns (baton, created)."""
        if not baton.idempotency_key:
            baton.idempotency_key = f"{baton.type}:{baton.initiative}:{baton.id}"
        baton.status = BatonStatus.PENDING
        key = self._key(baton)
        created = await self._redis.set_if_absent(key, baton.model_dump_json(), ttl)
        if created:
            return baton, True
        existing = await self.get(tenant=baton.tenant, idempotency_key=baton.idempotency_key)
        return existing or baton, False

    async def claim(self, baton: Baton, *, claimant: str, ttl: int) -> bool:
        """Transition pending → claimed for claimant. False if already claimed/done."""
        current = await self.get(tenant=baton.tenant, idempotency_key=baton.idempotency_key)
        if current is None:
            return False
        if current.status not in {BatonStatus.PENDING, BatonStatus.CLAIMED}:
            return False
        if current.status == BatonStatus.CLAIMED and current.claimed_by not in (None, claimant):
            return False
        current.status = BatonStatus.CLAIMED
        current.claimed_by = claimant
        current.updated_at = datetime.now(timezone.utc)
        await self.put(current, ttl=ttl)
        return True

    async def mark_running(self, baton: Baton, *, ttl: int) -> Baton:
        baton.status = BatonStatus.RUNNING
        return await self.put(baton, ttl=ttl)

    async def mark_done(self, baton: Baton, *, ttl: int, error: Optional[str] = None) -> Baton:
        baton.status = BatonStatus.FAILED if error else BatonStatus.DONE
        baton.error = error
        return await self.put(baton, ttl=ttl)
