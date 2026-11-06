"""ReadAgent — repo walks; claims read.walk batons."""

from __future__ import annotations

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.read.walk import ReadWalkProgramme
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.settings import ReadAgentSettings
from src.business_services.buzz_service import BuzzService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import MessageRead


class ReadAgent(BaseHermesAgent):
    role_id = "adh.read"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        batons: RedisBatonStore,
        tenants: TenantRegistryService,
        orchestrator: Orchestrator,
        walk: ReadWalkProgramme,
    ) -> None:
        settings = ReadAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings)
        self._tenants = tenants
        self._orchestrator = orchestrator
        self._walk = walk

    async def initialize(self) -> None:
        await super().initialize()
        self._orchestrator.bind_role(self.role_id)
        self._orchestrator.set_programme_runner(self._walk)
        rooms = [t.ops_room for t in self._tenants.active()]
        await self.start_ops_listeners(rooms)
        self.logger.info("ReadAgent listening", rooms=rooms)

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        tenant = self._tenants.by_ops_room(room)
        if tenant is None:
            return
        payload = message.payload or {}
        if (
            payload.get("status") == "baton_emitted"
            and payload.get("baton_type") == "read.walk"
            and payload.get("idempotency_key")
        ):
            baton = await self._batons.get(
                tenant=str(payload.get("tenant") or tenant.slug),
                idempotency_key=str(payload["idempotency_key"]),
            )
            if baton is not None:
                await self._walk.handle_baton(baton, room=room)
