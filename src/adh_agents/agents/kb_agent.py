"""KbAgent — OKF knowledge/ head patches."""

from __future__ import annotations

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.kb.enrich import KbEnrichProgramme
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.settings import KbAgentSettings
from src.business_services.buzz_service import BuzzService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import MessageRead


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
    ) -> None:
        settings = KbAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings)
        self._tenants = tenants
        self._orchestrator = orchestrator
        self._enrich = enrich

    async def initialize(self) -> None:
        await super().initialize()
        self._orchestrator.bind_role(self.role_id)
        self._orchestrator.set_programme_runner(self._enrich)
        rooms = [t.ops_room for t in self._tenants.active()]
        await self.start_ops_listeners(rooms)
        self.logger.info("KbAgent listening", rooms=rooms)

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        return None
