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


def pending_post_promote_key(slug: str) -> str:
    return f"adh:pm:awaiting-post-promote:{slug}"


def pending_validate_decisions_key(slug: str) -> str:
    return f"adh:pm:awaiting-validate-decisions:{slug}"


def pending_update_manifest_key(slug: str) -> str:
    return f"adh:pm:awaiting-update-manifest:{slug}"


def pending_impact_confirm_key(slug: str) -> str:
    return f"adh:pm:awaiting-impact-confirm:{slug}"


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
            or slug in getattr(self, "_awaiting_post_promote", {})
            or slug in getattr(self, "_awaiting_validate_decisions", {})
            or slug in getattr(self, "_awaiting_update_manifest", {})
            or slug in getattr(self, "_awaiting_impact_confirm", {})
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

    def _pending_post_promote_key(self, slug: str) -> str:
        return pending_post_promote_key(slug)

    def _pending_validate_decisions_key(self, slug: str) -> str:
        return pending_validate_decisions_key(slug)

    def _pending_update_manifest_key(self, slug: str) -> str:
        return pending_update_manifest_key(slug)

    def _pending_impact_confirm_key(self, slug: str) -> str:
        return pending_impact_confirm_key(slug)

    async def _store_pending_post_promote(
        self,
        tenant: TenantContext,
        room: str,
        initiative: str,
        prd_path_value: str,
        *,
        clean_after: bool = False,
    ) -> None:
        pending = {
            "room": room,
            "initiative": initiative,
            "prd_path": prd_path_value,
            "clean_after": clean_after,
        }
        self._awaiting_post_promote[tenant.slug] = pending
        try:
            await self._redis.set(
                self._pending_post_promote_key(tenant.slug),
                pending,
                self._ask_pending_ttl(),
            )
        except Exception:
            self.logger.exception("PM pending post-promote store failed", slug=tenant.slug)

    async def _load_pending_post_promote(self, slug: str) -> Optional[dict[str, Any]]:
        local = self._awaiting_post_promote.get(slug)
        if local:
            return local
        try:
            raw = await self._redis.get(self._pending_post_promote_key(slug), as_json=True)
        except Exception:
            self.logger.exception("PM pending post-promote load failed", slug=slug)
            return None
        if isinstance(raw, dict):
            self._awaiting_post_promote[slug] = raw
            return raw
        return None

    async def _clear_pending_post_promote(self, slug: str) -> None:
        self._awaiting_post_promote.pop(slug, None)
        try:
            await self._redis.delete(self._pending_post_promote_key(slug))
        except Exception:
            self.logger.exception("PM pending post-promote clear failed", slug=slug)

    async def _store_json_pending(
        self, local: dict[str, dict[str, Any]], key: str, slug: str, pending: dict[str, Any]
    ) -> None:
        local[slug] = pending
        try:
            await self._redis.set(key, pending, self._ask_pending_ttl())
        except Exception:
            self.logger.exception("PM pending store failed", key=key, slug=slug)

    async def _load_json_pending(
        self, local: dict[str, dict[str, Any]], key: str, slug: str
    ) -> Optional[dict[str, Any]]:
        cached = local.get(slug)
        if cached:
            return cached
        try:
            raw = await self._redis.get(key, as_json=True)
        except Exception:
            self.logger.exception("PM pending load failed", key=key, slug=slug)
            return None
        if isinstance(raw, dict):
            local[slug] = raw
            return raw
        return None

    async def _clear_json_pending(
        self, local: dict[str, dict[str, Any]], key: str, slug: str
    ) -> None:
        local.pop(slug, None)
        try:
            await self._redis.delete(key)
        except Exception:
            self.logger.exception("PM pending clear failed", key=key, slug=slug)

    async def _store_pending_validate_decisions(
        self, tenant: TenantContext, pending: dict[str, Any]
    ) -> None:
        await self._store_json_pending(
            self._awaiting_validate_decisions,
            self._pending_validate_decisions_key(tenant.slug),
            tenant.slug,
            pending,
        )

    async def _load_pending_validate_decisions(self, slug: str) -> Optional[dict[str, Any]]:
        return await self._load_json_pending(
            self._awaiting_validate_decisions,
            self._pending_validate_decisions_key(slug),
            slug,
        )

    async def _clear_pending_validate_decisions(self, slug: str) -> None:
        await self._clear_json_pending(
            self._awaiting_validate_decisions,
            self._pending_validate_decisions_key(slug),
            slug,
        )

    async def _store_pending_update_manifest(
        self, tenant: TenantContext, pending: dict[str, Any]
    ) -> None:
        await self._store_json_pending(
            self._awaiting_update_manifest,
            self._pending_update_manifest_key(tenant.slug),
            tenant.slug,
            pending,
        )

    async def _load_pending_update_manifest(self, slug: str) -> Optional[dict[str, Any]]:
        return await self._load_json_pending(
            self._awaiting_update_manifest,
            self._pending_update_manifest_key(slug),
            slug,
        )

    async def _clear_pending_update_manifest(self, slug: str) -> None:
        await self._clear_json_pending(
            self._awaiting_update_manifest,
            self._pending_update_manifest_key(slug),
            slug,
        )

    async def _store_pending_impact_confirm(
        self, tenant: TenantContext, pending: dict[str, Any]
    ) -> None:
        await self._store_json_pending(
            self._awaiting_impact_confirm,
            self._pending_impact_confirm_key(tenant.slug),
            tenant.slug,
            pending,
        )

    async def _load_pending_impact_confirm(self, slug: str) -> Optional[dict[str, Any]]:
        return await self._load_json_pending(
            self._awaiting_impact_confirm,
            self._pending_impact_confirm_key(slug),
            slug,
        )

    async def _clear_pending_impact_confirm(self, slug: str) -> None:
        await self._clear_json_pending(
            self._awaiting_impact_confirm,
            self._pending_impact_confirm_key(slug),
            slug,
        )

    async def _clear_all_post_promote(self, slug: str) -> None:
        await self._clear_pending_post_promote(slug)
        await self._clear_pending_validate_decisions(slug)
        await self._clear_pending_update_manifest(slug)
        await self._clear_pending_impact_confirm(slug)

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
