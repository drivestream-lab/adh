"""Redis pending state and inflight locks for Hermes PM."""

from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

import asyncio
from typing import Any, Optional

from src.business_services.hermes.lead_tokens import lock_token as _lock_token
from src.business_services.hermes.render_pm import _think_file_ref
from src.infra_services.pm_workspace_service import quality_path
from src.models.buzz_models import EventType
from src.models.hermes_models import HermesArtifactRead
from src.models.tenant_models import TenantContext


def pending_ask_key(slug: str) -> str:
    return f"adh:pm:awaiting-ask:{slug}"


def pending_recommend_key(slug: str) -> str:
    return f"adh:pm:awaiting-recommend:{slug}"


def pending_init_key(slug: str) -> str:
    return f"adh:pm:awaiting-init:{slug}"


def inflight_lock_key(slug: str, fingerprint: str) -> str:
    return f"adh:pm:inflight:{slug}:{fingerprint}"


def ask_pending_ttl_seconds(
    *, ask_wait_seconds: float, outline_lock_seconds: int, grace_seconds: int
) -> int:
    """Keep ask durable past the wait window so expiry cannot free an outline slot."""
    wait = max(0, int(ask_wait_seconds))
    grace = max(0, int(grace_seconds))
    lock = max(60, int(outline_lock_seconds))
    return max(lock, wait + grace)


class PendingMixin:
    """Awaiting-ask/recommend/init + outline inflight locks."""

    def _tenant_has_open_work(self, slug: str) -> bool:
        if any(token.startswith(f"{slug}:") for token in self._inflight):
            return True
        return (
            slug in self._awaiting_init
            or slug in self._awaiting_ask
            or slug in self._awaiting_recommend
        )

    def _pending_ask_key(self, slug: str) -> str:
        return pending_ask_key(slug)

    def _pending_recommend_key(self, slug: str) -> str:
        return pending_recommend_key(slug)

    def _ask_pending_ttl(self) -> int:
        return ask_pending_ttl_seconds(
            ask_wait_seconds=float(self._settings.pm_ask_wait_seconds),
            outline_lock_seconds=int(self._settings.outline_lock_seconds),
            grace_seconds=int(self._settings.pm_ask_grace_seconds),
        )

    async def _store_pending_ask(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        thinks: list[HermesArtifactRead],
        quality: HermesArtifactRead,
        forks: list[Any],
    ) -> None:
        pending = {
            "room": room,
            "outline": outline,
            "initiative": initiative,
            "forks": forks,
            "think_paths": [str(_think_file_ref(item)["path"]) for item in thinks],
            "quality_path": str(quality.payload.get("path") or quality_path(initiative)),
        }
        self._awaiting_ask[tenant.slug] = pending
        try:
            await self._redis.set(
                self._pending_ask_key(tenant.slug),
                pending,
                self._ask_pending_ttl(),
            )
        except Exception:
            self.logger.exception("PM pending ask store failed", slug=tenant.slug)

    async def _load_pending_ask(self, slug: str) -> Optional[dict[str, Any]]:
        local = self._awaiting_ask.get(slug)
        if local:
            return local
        try:
            raw = await self._redis.get(self._pending_ask_key(slug), as_json=True)
        except Exception:
            self.logger.exception("PM pending ask load failed", slug=slug)
            return None
        if isinstance(raw, dict):
            self._awaiting_ask[slug] = raw
            return raw
        return None

    async def _clear_pending_ask(self, slug: str) -> None:
        self._awaiting_ask.pop(slug, None)
        self._ask_answers.pop(slug, None)
        try:
            await self._redis.delete(self._pending_ask_key(slug))
        except Exception:
            self.logger.exception("PM pending ask clear failed", slug=slug)

    async def _store_pending_recommend(
        self,
        tenant: TenantContext,
        room: str,
        initiative: str,
        pick: str,
        path: str,
        think_paths: Optional[list[str]] = None,
    ) -> None:
        pending = {
            "room": room,
            "initiative": initiative,
            "recommend": pick,
            "path": path,
            "think_paths": list(think_paths or []),
        }
        self._awaiting_recommend[tenant.slug] = pending
        try:
            await self._redis.set(
                self._pending_recommend_key(tenant.slug),
                pending,
                int(self._settings.outline_lock_seconds),
            )
        except Exception:
            self.logger.exception("PM pending recommend store failed", slug=tenant.slug)

    async def _load_pending_recommend(self, slug: str) -> Optional[dict[str, Any]]:
        local = self._awaiting_recommend.get(slug)
        if local:
            return local
        try:
            raw = await self._redis.get(self._pending_recommend_key(slug), as_json=True)
        except Exception:
            self.logger.exception("PM pending recommend load failed", slug=slug)
            return None
        if isinstance(raw, dict):
            self._awaiting_recommend[slug] = raw
            return raw
        return None

    async def _clear_pending_recommend(self, slug: str) -> None:
        self._awaiting_recommend.pop(slug, None)
        try:
            await self._redis.delete(self._pending_recommend_key(slug))
        except Exception:
            self.logger.exception("PM pending recommend clear failed", slug=slug)

    async def _wait_ask_answers(self, slug: str, timeout: float) -> dict[str, str]:
        event = asyncio.Event()
        self._ask_events[slug] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return dict(self._ask_answers.get(slug) or {})
        except asyncio.TimeoutError:
            return {}
        finally:
            self._ask_events.pop(slug, None)

    def _pending_init_key(self, slug: str) -> str:
        return pending_init_key(slug)

    async def _ask_for_init(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        fingerprint: str,
        source_id: str,
    ) -> None:
        listing = self._workspace.inventory(tenant)
        occupied = ", ".join(listing.inits) if listing.inits else "(none)"
        pending = {
            "outline": outline,
            "fingerprint": fingerprint,
            "source_id": source_id,
            "room": room,
        }
        self._awaiting_init[tenant.slug] = pending
        try:
            await self._redis.set(
                self._pending_init_key(tenant.slug),
                pending,
                self._settings.outline_lock_seconds,
            )
        except Exception:
            self.logger.exception("PM pending INIT store failed", slug=tenant.slug)
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.need-init",
                {
                    "meta_repo": tenant.meta_repo,
                    "occupied_inits": occupied,
                    "prefix": tenant.init_prefix,
                },
            ),
            EventType.PROGRESS,
            {
                "status": "need_init",
                "outline_fingerprint": fingerprint,
                "programme_slug": tenant.slug,
                "source_message_id": source_id,
                "hop": "t0",
            },
        )

    async def _load_pending_init(self, slug: str) -> Optional[dict[str, Any]]:
        local = self._awaiting_init.get(slug)
        if local:
            return local
        try:
            raw = await self._redis.get(self._pending_init_key(slug), as_json=True)
        except Exception:
            self.logger.exception("PM pending INIT load failed", slug=slug)
            return None
        return raw if isinstance(raw, dict) else None

    async def _clear_pending_init(self, slug: str) -> None:
        self._awaiting_init.pop(slug, None)
        try:
            await self._redis.delete(self._pending_init_key(slug))
        except Exception:
            self.logger.exception("PM pending INIT clear failed", slug=slug)

    def _track_outline_task(self, slug: str, task: asyncio.Task[None]) -> None:
        self._outline_tasks[slug] = task
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)

    def _lock_key(self, slug: str, fingerprint: str) -> str:
        return f"adh:pm:inflight:{slug}:{fingerprint}"

    async def _claim_outline(self, slug: str, fingerprint: str, source_id: str) -> bool:
        token = _lock_token(slug, fingerprint)
        if token in self._inflight:
            return False
        try:
            won = await self._redis.set_if_absent(
                self._lock_key(slug, fingerprint),
                source_id,
                self._settings.outline_lock_seconds,
            )
        except Exception:
            self.logger.exception("PM outline lock failed; using process memory")
            won = token not in self._inflight
        if not won:
            return False
        self._inflight[token] = source_id
        return True

    async def _release_outline(self, slug: str, fingerprint: str) -> None:
        token = _lock_token(slug, fingerprint)
        self._inflight.pop(token, None)
        try:
            await self._redis.delete(self._lock_key(slug, fingerprint))
        except Exception:
            self.logger.exception("PM outline unlock failed", fingerprint=fingerprint, slug=slug)
