"""PEAgent — Gate-1; embeds Orchestrator; claims pe.review batons."""

from __future__ import annotations

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.pe.review import PeReviewProgramme
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.settings import PeAgentSettings
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import MessageKind, MessageRead


class PEAgent(BaseHermesAgent):
    role_id = "adh.pe"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        batons: RedisBatonStore,
        tenants: TenantRegistryService,
        orchestrator: Orchestrator,
        pe: PeReviewProgramme,
    ) -> None:
        settings = PeAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings)
        self._tenants = tenants
        self._orchestrator = orchestrator
        self._pe = pe
        self._lead = HermesSettings.get_instance().lead_handle

    async def initialize(self) -> None:
        await super().initialize()
        self._orchestrator.bind_role(self.role_id)
        self._orchestrator.set_programme_runner(self._pe)
        rooms = [t.ops_room for t in self._tenants.active()]
        await self.start_ops_listeners(rooms)
        self.logger.info("PEAgent listening", rooms=rooms)

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        tenant = self._tenants.by_ops_room(room)
        if tenant is None:
            return
        payload = message.payload or {}
        if (
            payload.get("status") == "baton_emitted"
            and payload.get("baton_type") == "pe.review"
            and payload.get("idempotency_key")
        ):
            baton = await self._batons.get(
                tenant=str(payload.get("tenant") or tenant.slug),
                idempotency_key=str(payload["idempotency_key"]),
            )
            if baton is not None:
                await self._pe.handle_baton(baton, room=room)
                return
        if message.kind == MessageKind.MESSAGE and (message.identity_handle or "") == self._lead:
            await self._orchestrator.handle_lead_message(tenant, room, message)
