"""KbAgent — OKF knowledge/ head patches."""

from __future__ import annotations

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.kb.enrich import KbEnrichProgramme
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.runtime.work_models import AWAITING_AUTHORIZATION, AWAITING_JUDGMENT
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import KbAgentSettings
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import MessageKind, MessageRead


class KbAgent(BaseHermesAgent):
    role_id = "adh.kb"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        batons: RedisBatonStore,
        tenants: TenantRegistryService,
        orchestrator: Orchestrator,
        enrich: KbEnrichProgramme,
        work_store: AgentWorkStore,
    ) -> None:
        settings = KbAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings)
        self._tenants = tenants
        self._orchestrator = orchestrator
        self._enrich = enrich
        self._work_store = work_store
        self._lead = HermesSettings.get_instance().lead_handle

    async def initialize(self) -> None:
        await super().initialize()
        self._orchestrator.bind_role(self.role_id)
        self._orchestrator.set_programme_runner(self._enrich)
        rooms = [t.ops_room for t in self._tenants.active()]
        await self.start_ops_listeners(rooms)
        await self._catch_up_pending_batons()
        self.logger.info("KbAgent listening", rooms=rooms)

    async def _catch_up_pending_batons(self) -> None:
        ttl = int(self._agent_settings.baton_ttl_seconds)
        for tenant in self._tenants.active():
            await self._batons.reclaim_stale(tenant=tenant.slug, max_age_seconds=ttl)
            pending = await self._batons.list_pending_for(
                tenant=tenant.slug, to_role=self.role_id, baton_type="kb.enrich"
            )
            for baton in pending:
                await self._enrich.handle_baton(baton, room=tenant.ops_room)

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        tenant = self._tenants.by_ops_room(room)
        if tenant is None:
            return
        payload = message.payload or {}
        if (
            payload.get("status") == "baton_emitted"
            and payload.get("baton_type") == "kb.enrich"
            and payload.get("idempotency_key")
        ):
            baton = await self._batons.get(
                tenant=str(payload.get("tenant") or tenant.slug),
                idempotency_key=str(payload["idempotency_key"]),
            )
            if baton is not None:
                await self._enrich.handle_baton(baton, room=room)
                return
        if message.kind == MessageKind.MESSAGE and (message.identity_handle or "") == self._lead:
            body = (message.body or "").strip()
            # U2: KB silent unless open knowledge gate or explicit resume.
            if "resume" in body.lower():
                await self._orchestrator.handle_lead_message(tenant, room, message)
                return
            active = await self._work_store.list_active(tenant.slug, self.role_id)
            open_gates = [
                s
                for s in active
                if s.awaiting in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION)
                and s.open_brief is not None
            ]
            if open_gates:
                await self._orchestrator.handle_lead_message(tenant, room, message)
