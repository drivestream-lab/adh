"""Short-TTL presence keys — Redis live only (never chat)."""

from __future__ import annotations

from injector import inject

from src.infra_services.redis_service import RedisService
from src.logging import get_logger

logger = get_logger()

_PREFIX = "adh:presence"


class PresenceService:
    """Mark role listening/busy for a tenant hub."""

    @inject
    def __init__(self, redis: RedisService) -> None:
        self._redis = redis

    def _key(self, tenant: str, role_id: str) -> str:
        return f"{_PREFIX}:{tenant}:{role_id}"

    async def heartbeat(
        self,
        *,
        tenant: str,
        role_id: str,
        state: str = "listening",
        ttl_seconds: int = 120,
    ) -> None:
        await self._redis.set(
            self._key(tenant, role_id),
            state,
            ttl=max(30, int(ttl_seconds)),
        )

    async def get(self, *, tenant: str, role_id: str) -> str | None:
        raw = await self._redis.get(self._key(tenant, role_id))
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8")
        return str(raw)
