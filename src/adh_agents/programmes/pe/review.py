"""PE review programme — claims pe.review, fans out read batons, asks Lead (caps later)."""

from __future__ import annotations

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.runtime.work_models import PROGRAMME_PE, AgentWorkSession
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import PeAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext


class PeReviewProgramme(BaseBusinessService):
    programme_id = PROGRAMME_PE
    role_id = "adh.pe"

    @inject
    def __init__(
        self,
        store: AgentWorkStore,
        batons: RedisBatonStore,
        poster: HermesBuzzPoster,
    ) -> None:
        super().__init__()
        self._store = store
        self._batons = batons
        self._poster = poster
        self._settings = PeAgentSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        await self._poster.post_status(
            room,
            f"PE programme bound for {session.initiative or session.work_id}.",
            EventType.PROGRESS,
        )

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        await self._poster.post_status(
            room,
            f"PE recorded `{token}` for {session.initiative or session.work_id}.",
            EventType.PROGRESS,
        )

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        live = await self._store.load(tenant.slug, self.role_id, work_id)
        if live is None:
            await self._poster.post_status(
                room,
                f"Cannot resume PE work `{work_id}` — no live session.",
                EventType.STALL,
            )
            return
        await self._poster.post_status(
            room,
            f"Resuming PE work `{work_id}` at **{live.stage or 'pe'}**.",
            EventType.PROGRESS,
        )

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        return []

    async def handle_baton(self, baton: Baton, *, room: str) -> Rollup:
        """Claim pe.review and open a role-scoped work session."""
        ttl = int(self._settings.baton_ttl_seconds)
        claimed = await self._batons.claim(baton, claimant=self.role_id, ttl=ttl)
        if not claimed:
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="claim failed (already claimed or missing)",
                correlation_id=baton.correlation_id,
                error="claim_failed",
            )
        await self._batons.mark_running(baton, ttl=ttl)
        init = (baton.initiative or baton.id).strip().upper()
        session = AgentWorkSession(
            tenant_slug=baton.tenant,
            role_id=self.role_id,
            room=room or baton.ops_room,
            work_id=init,
            initiative=init if baton.initiative else None,
            programme=self.programme_id,
            stage="gate1_review",
            slots={
                "pr_url": str((baton.payload or {}).get("pr_url") or ""),
                "baton_id": baton.id,
            },
        )
        await self._store.save(session)
        await self._poster.post_status(
            room or baton.ops_room,
            (
                f"PE claimed `pe.review` for {init}. "
                f"PR: {(baton.payload or {}).get('pr_url') or 'n/a'}. "
                "Read fan-out next (adh.read)."
            ),
            EventType.START,
            {"status": "pe_claimed", "initiative": init, "baton_id": baton.id},
        )
        # Emit one read.walk baton for meta as a starter fan-out signal.
        walk = Baton(
            type="read.walk",
            from_role=self.role_id,
            to_role="adh.read",
            tenant=baton.tenant,
            ops_room=baton.ops_room,
            initiative=init,
            idempotency_key=f"read.walk:{baton.tenant}:{init}:meta",
            payload={"repo": "meta", "reason": "gate1_pe_review", "parent_baton": baton.id},
            artefact_refs=list(baton.artefact_refs or []),
        )
        stored_walk, created = await self._batons.create_pending(walk, ttl=ttl)
        notice = (
            f"baton `read.walk` → `adh.read` (init={init}; "
            f"correlation={stored_walk.correlation_id})"
        )
        if not created:
            notice = f"(idempotent) {notice}"
        await self._poster.post_status(
            room or baton.ops_room,
            notice,
            EventType.PROGRESS,
            {
                "status": "baton_emitted",
                "baton_type": "read.walk",
                "baton_id": stored_walk.id,
                "idempotency_key": stored_walk.idempotency_key,
                "initiative": init,
                "tenant": baton.tenant,
                "created": created,
            },
        )
        done = await self._batons.mark_done(baton, ttl=ttl)
        return Rollup(
            baton_id=done.id,
            role=self.role_id,
            status=done.status,
            summary=f"PE claimed review for {init}; emitted read.walk",
            correlation_id=done.correlation_id,
            artefact_refs=list(done.artefact_refs or []),
            tools_used=["baton.claim", "baton.emit_read_walk"],
        )
