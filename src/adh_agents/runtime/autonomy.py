"""Autonomy policy — human waits; god plays recommend tokens only."""

from __future__ import annotations

from enum import Enum

from injector import inject

from src.adh_agents.settings import AdhAutonomySettings
from src.infra_services.redis_service import RedisService
from src.logging import get_logger
from src.models.hermes.intent_models import JudgmentRequest

logger = get_logger()

_HALT_TOKENS = frozenset(
    {
        "hold",
        "park",
        "skip",
        "none",
        "revise",
        "iterate",
        "delete task",
    }
)
_CHAIN_PREFIX = "adh:autonomy:chain"


class AutonomyMode(str, Enum):
    HUMAN = "human"
    GOD = "god"


class AutonomyPolicy:
    """Resolve whether GateOpener should wait or auto-take."""

    @inject
    def __init__(self, redis: RedisService) -> None:
        self._redis = redis
        self._settings = AdhAutonomySettings.get_instance()
        raw = (self._settings.autonomy_mode or "human").strip().lower()
        self.mode = AutonomyMode.GOD if raw == "god" else AutonomyMode.HUMAN
        logger.info("Autonomy policy loaded", mode=self.mode.value)

    @property
    def is_god(self) -> bool:
        return self.mode == AutonomyMode.GOD

    def resolve_token(self, brief: JudgmentRequest) -> str | None:
        """Return recommend when it is an exact reply_token; else None (halt)."""
        recommend = (brief.recommend or "").strip()
        tokens = [str(t).strip() for t in (brief.reply_tokens or []) if str(t).strip()]
        if not recommend or recommend not in tokens:
            return None
        lowered = recommend.lower()
        if lowered in _HALT_TOKENS:
            return None
        if lowered == "discard local" and not self._settings.god_allow_discard:
            return None
        return recommend

    async def begin_chain(self, *, tenant: str, initiative: str) -> None:
        key = f"{_CHAIN_PREFIX}:{tenant}:{initiative.strip().upper()}"
        await self._redis.set(key, "0", ttl=3600)

    async def record_take(self, *, tenant: str, initiative: str, purpose: str) -> tuple[bool, str]:
        """Return (ok, reason). Caps chain length only.

        Same-purpose re-entry is allowed (``another round`` / iterate / findings
        loops). Halt only when the hard chain cap is hit — never on duplicate
        purpose alone.
        """
        init = initiative.strip().upper()
        key = f"{_CHAIN_PREFIX}:{tenant}:{init}"
        raw = await self._redis.get(key)
        count = 0
        seen: list[str] = []
        if raw:
            text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
            parts = [p for p in text.split("|") if p]
            if parts and parts[0].isdigit():
                count = int(parts[0])
                seen = parts[1:]
            elif text.isdigit():
                count = int(text)
        cap = int(self._settings.god_chain_cap)
        if count >= cap:
            return False, f"god chain cap {cap} reached"
        purpose_key = (purpose or "").strip() or "gate"
        seen.append(purpose_key)
        # Keep a short observability trail; uniqueness is not enforced.
        trail = seen[-cap:] if len(seen) > cap else seen
        payload = f"{count + 1}|" + "|".join(trail)
        await self._redis.set(key, payload, ttl=3600)
        return True, "ok"
