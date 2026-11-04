"""Hermes session persistence — one Redis key per tenant."""

from __future__ import annotations

from typing import Optional

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.configs.hermes_settings import HermesSettings
from src.infra_services.redis_service import RedisService
from src.models.hermes.session_models import HermesSession

_KEY_PREFIX = "adh:hermes:session:"


def session_key(slug: str) -> str:
    return f"{_KEY_PREFIX}{slug}"


class HermesSessionStoreService(BaseBusinessService):
    """Load / save / clear the single JSON session document for a tenant."""

    @inject
    def __init__(self, redis: RedisService) -> None:
        super().__init__()
        self._redis = redis
        self._ttl = HermesSettings.get_instance().outline_lock_seconds

    async def load(self, slug: str) -> Optional[HermesSession]:
        raw = await self._redis.get(session_key(slug), as_json=True)
        if raw is None:
            return None
        return HermesSession.model_validate(raw)

    async def save(self, session: HermesSession) -> None:
        session.touch()
        await self._redis.set(
            session_key(session.tenant_slug),
            session.model_dump(mode="json"),
            ttl=self._ttl,
        )
        self.logger.info(
            "Saved Hermes session",
            slug=session.tenant_slug,
            stage=session.stage,
            awaiting=session.awaiting,
        )

    async def clear(self, slug: str) -> None:
        await self._redis.delete(session_key(slug))
        self.logger.info("Cleared Hermes session", slug=slug)
