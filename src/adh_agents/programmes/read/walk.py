"""Read walk programme — filesystem port (codegraph stub later)."""

from __future__ import annotations

from pathlib import Path

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.ports.filesystem import list_repo_sketch
from src.adh_agents.runtime.work_models import PROGRAMME_READ, AgentWorkSession
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import ReadAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.configs.orchestrator_settings import OrchestratorSettings
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext


class ReadWalkProgramme(BaseBusinessService):
    programme_id = PROGRAMME_READ
    role_id = "adh.read"

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
        self._settings = ReadAgentSettings.get_instance()
        self._orch = OrchestratorSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        await self._poster.post_status(
            room,
            f"Read programme bound for {session.work_id}.",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        return None

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        await self._poster.post_status(
            room,
            f"Resume read walk `{work_id}` (no-op if finished).",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

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
        root = Path(self._orch.workspace_root)
        sketch = list_repo_sketch(root, limit=40)
        summary = f"read.walk sketch ({len(sketch)} paths) under {root}"
        await self._poster.post_status(
            room or baton.ops_room,
            f"Read rollup for {baton.initiative or baton.id}: {summary}",
            EventType.DONE,
            {"status": "read_rollup", "paths": sketch[:20], "baton_id": baton.id},
            identity_handle=self.role_id,
        )
        done = await self._batons.mark_done(baton, ttl=ttl)
        return Rollup(
            baton_id=done.id,
            role=self.role_id,
            status=done.status,
            summary=summary,
            correlation_id=done.correlation_id,
            artefact_refs=sketch[:20],
            tools_used=["filesystem.list"],
        )
