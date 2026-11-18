"""Per-repo Redis leases for the Coder swarm (C.13 / C.17)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from injector import inject

from src.infra_services.redis_service import RedisService
from src.logging import get_logger

logger = get_logger()

_PREFIX = "adh:coder:lease"


def lease_key(*, tenant: str, repo: str) -> str:
    short = (repo or "").strip().rsplit("/", 1)[-1]
    return f"{_PREFIX}:{tenant}:{short}"


@dataclass(frozen=True)
class LeaseResult:
    acquired: bool
    key: str
    holder: str = ""
    reason: str = ""


class CoderRepoLeaseStore:
    """NX lease: one active coder per repo; clip swarm by ``max_parallel_coders``."""

    @inject
    def __init__(self, redis: RedisService) -> None:
        self._redis = redis
        self._prefix = _PREFIX

    def _key(self, *, tenant: str, repo: str) -> str:
        short = (repo or "").strip().rsplit("/", 1)[-1]
        return f"{self._prefix}:{tenant}:{short}"

    async def try_acquire(
        self,
        *,
        tenant: str,
        repo: str,
        holder: str,
        ttl_seconds: int,
    ) -> LeaseResult:
        key = self._key(tenant=tenant, repo=repo)
        payload = {
            "holder": holder,
            "repo": (repo or "").strip().rsplit("/", 1)[-1],
            "tenant": tenant,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }
        ok = await self._redis.set_if_absent(key, json.dumps(payload), ttl_seconds)
        if ok:
            logger.info("coder repo lease acquired", key=key, holder=holder)
            return LeaseResult(acquired=True, key=key, holder=holder)
        raw = await self._redis.get(key)
        existing_holder = _holder_from_raw(raw)
        if existing_holder == holder:
            # Same worker renews / re-enters.
            await self._redis.set(key, json.dumps(payload), ttl=ttl_seconds)
            return LeaseResult(acquired=True, key=key, holder=holder, reason="renewed")
        return LeaseResult(
            acquired=False,
            key=key,
            holder=existing_holder,
            reason="held",
        )

    async def release(self, *, tenant: str, repo: str, holder: str) -> bool:
        key = self._key(tenant=tenant, repo=repo)
        raw = await self._redis.get(key)
        if raw is None:
            return True
        existing_holder = _holder_from_raw(raw)
        if existing_holder and existing_holder != holder:
            return False
        await self._redis.delete(key)
        logger.info("coder repo lease released", key=key, holder=holder)
        return True

    async def count_held(self, *, tenant: str) -> int:
        keys = await self._redis.keys(f"{self._prefix}:{tenant}:*")
        return len(keys or [])

    async def clip_ready(
        self,
        repos: list[str] | tuple[str, ...],
        *,
        tenant: str,
        max_parallel: int,
    ) -> list[str]:
        """Return repos that may start now given held leases + cap (stable order)."""
        cap = max(1, int(max_parallel))
        held = await self.count_held(tenant=tenant)
        slots = max(0, cap - held)
        if slots <= 0:
            return []
        out: list[str] = []
        for repo in repos:
            short = (repo or "").strip().rsplit("/", 1)[-1]
            if not short:
                continue
            key = self._key(tenant=tenant, repo=short)
            if await self._redis.get(key) is not None:
                continue
            out.append(short)
            if len(out) >= slots:
                break
        return out


def _holder_from_raw(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip().startswith("{"):
        return ""
    try:
        return str(json.loads(raw).get("holder") or "")
    except Exception:
        return ""
