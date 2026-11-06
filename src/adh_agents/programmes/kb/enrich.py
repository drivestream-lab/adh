"""KB enrich programme — patch knowledge/ heads when triggered (no initiative folders)."""

from __future__ import annotations

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.runtime.work_models import PROGRAMME_KB, AgentWorkSession
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import KbAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext


class KbEnrichProgramme(BaseBusinessService):
    programme_id = PROGRAMME_KB
    role_id = "adh.kb"

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
        self._settings = KbAgentSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        await self._poster.post_status(
            room, f"KB programme bound for {session.work_id}.", EventType.PROGRESS
        )

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        return None

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        await self._poster.post_status(room, f"Resume KB enrich `{work_id}`.", EventType.PROGRESS)

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        return []

    async def handle_baton(self, baton: Baton, *, room: str) -> Rollup:
        ttl = int(self._settings.baton_ttl_seconds)
        claimed = await self._batons.claim(baton, claimant=self.role_id, ttl=ttl)
        if not claimed:
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="claim failed",
                correlation_id=baton.correlation_id,
                error="claim_failed",
            )
        await self._batons.mark_running(baton, ttl=ttl)
        # Heads-only: announce intent; concrete patches land when meta knowledge/ exists.
        await self._poster.post_status(
            room or baton.ops_room,
            (
                f"KB enrich claimed for {baton.initiative or baton.id}. "
                "Will patch OKF heads under tenant meta `knowledge/` only."
            ),
            EventType.DONE,
            {"status": "kb_claimed", "baton_id": baton.id},
        )
        done = await self._batons.mark_done(baton, ttl=ttl)
        return Rollup(
            baton_id=done.id,
            role=self.role_id,
            status=done.status,
            summary="KB enrich claimed (heads-only policy)",
            correlation_id=done.correlation_id,
            tools_used=["kb.policy_heads_only"],
        )
