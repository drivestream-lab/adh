"""ReadAgent — repo walks; claims read.walk batons."""

from __future__ import annotations

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.read.walk import ReadWalkProgramme
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.runtime.presence import PresenceService
from src.adh_agents.runtime.room_resolve import listen_rooms_for_tenants, resolve_tenant_for_room
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
        presence: PresenceService,
    ) -> None:
        settings = ReadAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings, presence=presence)
        self._tenants = tenants
        self._orchestrator = orchestrator
        self._walk = walk

    async def initialize(self) -> None:
        await super().initialize()
        self._orchestrator.bind_role(self.role_id)
        self._orchestrator.set_programme_runner(self._walk)
        for tenant in self._tenants.active():
            await self.ensure_hub_member(tenant.ops_room)
        rooms = await listen_rooms_for_tenants(self._buzz, self._tenants)
        await self.start_ops_listeners(rooms)
        await self._catch_up_pending_batons()
        self.start_listen_refresh_loop(
            lambda: listen_rooms_for_tenants(self._buzz, self._tenants),
            interval_seconds=15.0,
        )
        self.logger.info("ReadAgent listening", rooms=rooms)

    async def _catch_up_pending_batons(self) -> None:
        """Claim read.walk batons parked before this worker was online."""
        ttl = int(self._agent_settings.baton_ttl_seconds)
        for tenant in self._tenants.active():
            await self._batons.reclaim_stale(tenant=tenant.slug, max_age_seconds=ttl)
            pending = await self._batons.list_pending_for(
                tenant=tenant.slug, to_role=self.role_id, baton_type="read.walk"
            )
            for baton in pending:
                await self._walk.handle_baton(baton, room=baton.ops_room or tenant.ops_room)

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        tenant = await resolve_tenant_for_room(self._tenants, self._buzz, room)
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
