"""Outline inflight locks for Hermes authoring (ask/recommend pending retired → session)."""

from __future__ import annotations

# pyright: reportAttributeAccessIssue=false


from src.business_services.hermes.lead_tokens import lock_token as _lock_token
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext


def inflight_lock_key(slug: str, fingerprint: str) -> str:
    return f"adh:pm:inflight:{slug}:{fingerprint}"


class PendingMixin:
    """Outline inflight locks only — programme waits live on HermesSession."""

    def _tenant_has_open_work(self, slug: str) -> bool:
        if any(token.startswith(f"{slug}:") for token in self._inflight):
            return True
        return False

    def _lock_key(self, slug: str, fingerprint: str) -> str:
        return inflight_lock_key(slug, fingerprint)

    async def _claim_outline(self, slug: str, fingerprint: str, source_id: str) -> bool:
        token = _lock_token(slug, fingerprint)
        if token in self._inflight:
            return False
        ttl = int(self._settings.outline_lock_seconds)
        try:
            claimed = await self._redis.set_if_absent(
                self._lock_key(slug, fingerprint), source_id, ttl
            )
        except Exception:
            self.logger.exception("PM outline lock failed", slug=slug)
            return False
        if not claimed:
            return False
        self._inflight[token] = source_id
        return True

    async def _release_outline(self, slug: str, fingerprint: str) -> None:
        token = _lock_token(slug, fingerprint)
        self._inflight.pop(token, None)
        try:
            await self._redis.delete(self._lock_key(slug, fingerprint))
        except Exception:
            self.logger.exception("PM outline unlock failed", slug=slug)

    async def _clear_all_post_promote(self, slug: str) -> None:
        collaborator = getattr(self, "_collaborator", None)
        if collaborator is None:
            return
        store = getattr(collaborator, "_store", None)
        clear = getattr(store, "clear", None) if store is not None else None
        if clear is None:
            return
        result = clear(slug)
        if hasattr(result, "__await__"):
            await result

    async def _halt_programme(self, tenant: TenantContext, room: str) -> None:
        slug = tenant.slug
        for token in [key for key in list(self._inflight) if key.startswith(f"{slug}:")]:
            self._inflight.pop(token, None)
        task = self._outline_tasks.pop(slug, None)
        if task is not None and not task.done():
            task.cancel()
        await self._clear_all_post_promote(slug)
        authoring = getattr(self, "_authoring", None)
        if authoring is not None:
            store = getattr(authoring, "_store", None)
            if store is not None:
                result = store.clear(slug)
                if hasattr(result, "__await__"):
                    await result
        initiative = self._open_initiative.get(slug, "") or "n/a"
        await self._status(
            room,
            f"Stopped programme work for {initiative}.",
            EventType.STALL,
            {"status": "stopped", "programme_slug": slug},
        )

    async def _try_lead_stop(self, tenant: TenantContext, room: object, message: object) -> bool:
        from src.models.buzz_models import MessageKind, MessageRead

        if not isinstance(message, MessageRead):
            return False
        if message.kind != MessageKind.MESSAGE:
            return False
        if (message.identity_handle or "") != self._settings.lead_handle:
            return False
        if (message.body or "").strip().lower() != "stop":
            return False
        await self._halt_programme(tenant, str(room))
        return True
