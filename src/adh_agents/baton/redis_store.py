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

    async def list_for_tenant(
        self,
        *,
        tenant: str,
        to_role: str | None = None,
        baton_type: str | None = None,
        status: BatonStatus | None = None,
    ) -> list[Baton]:
        """List batons for a tenant with optional filters."""
        keys = await self._redis.keys(f"{self._prefix}:{tenant}:*")
        found: list[Baton] = []
        for key in keys:
            raw = await self._redis.get(key)
            if raw is None:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                baton = Baton.model_validate_json(raw)
            except Exception:
                logger.exception("skip corrupt baton key", key=key)
                continue
            if status is not None and baton.status != status:
                continue
            if to_role is not None and baton.to_role != to_role:
                continue
            if baton_type is not None and baton.type != baton_type:
                continue
            found.append(baton)
        return found

    async def list_pending_for(
        self, *, tenant: str, to_role: str, baton_type: str | None = None
    ) -> list[Baton]:
        """Pending batons for a role (hire-order catch-up when worker boots after emit)."""
        return await self.list_for_tenant(
            tenant=tenant,
            to_role=to_role,
            baton_type=baton_type,
            status=BatonStatus.PENDING,
        )

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

    async def expire(self, baton: Baton) -> Baton:
        """Mark expired and drop the Redis key (idempotency slot frees for retry)."""
        baton.status = BatonStatus.EXPIRED
        baton.updated_at = datetime.now(timezone.utc)
        await self._redis.delete(self._key(baton))
        logger.info(
            "Baton expired",
            tenant=baton.tenant,
            key=baton.idempotency_key or baton.id,
            baton_type=baton.type,
        )
        return baton

    async def reclaim_stale(
        self,
        *,
        tenant: str,
        max_age_seconds: int,
        statuses: set[BatonStatus] | None = None,
    ) -> list[Baton]:
        """Expire CLAIMED/RUNNING batons whose updated_at is older than max_age."""
        watch = statuses or {BatonStatus.CLAIMED, BatonStatus.RUNNING}
        now = datetime.now(timezone.utc)
        reclaimed: list[Baton] = []
        for baton in await self.list_for_tenant(tenant=tenant):
            if baton.status not in watch:
                continue
            age = (now - baton.updated_at).total_seconds() if baton.updated_at else 0
            if age < max_age_seconds:
                continue
            reclaimed.append(await self.expire(baton))
            logger.warning(
                "Baton reclaimed (stale)",
                tenant=tenant,
                baton_type=baton.type,
                age_seconds=int(age),
                key=baton.idempotency_key or baton.id,
            )
        return reclaimed
