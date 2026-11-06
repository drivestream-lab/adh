"""PMAgent — product/requirements delivery on BaseHermesAgent."""

from __future__ import annotations

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.models import Baton
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.settings import PmAgentSettings
from src.business_services.buzz_service import BuzzService
from src.business_services.hermes_service import HermesService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import MessageRead


class PMAgent(BaseHermesAgent):
    """Product / requirements agent. Owns ops listen; delegates lane logic to HermesService programmes."""

    role_id = "adh.pm"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        batons: RedisBatonStore,
        hermes: HermesService,
        tenants: TenantRegistryService,
    ) -> None:
        settings = PmAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings)
        self._hermes = hermes
        self._tenants = tenants
        self._pm_settings = settings

    async def initialize(self) -> None:
        await super().initialize()
        rooms = [tenant.ops_room for tenant in self._tenants.active()]
        await self.start_ops_listeners(rooms)
        for room in rooms:
            # Replay recent unacked outlines (parity with former HermesService catch-up).
            await self._hermes.catch_up_ops(room)
        self.logger.info("PMAgent listening", rooms=rooms)

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        await self._hermes.on_room_message(room, message)

    async def emit_pe_review_after_draft_pr(
        self,
        *,
        tenant_slug: str,
        ops_room: str,
        initiative: str,
        pr_url: str = "",
        artefact_refs: list[str] | None = None,
    ) -> Baton | None:
        """Wave 0a: park pe.review for Wave 0b PE worker (Phase1 #1B)."""
        if not self._pm_settings.emit_pe_review_baton:
            return None
        baton = Baton(
            type="pe.review",
            from_role=self.role_id,
            to_role="adh.pe",
            tenant=tenant_slug,
            ops_room=ops_room,
            initiative=initiative,
            idempotency_key=f"pe.review:{tenant_slug}:{initiative}:{pr_url or 'draft'}",
            payload={
                "pr_url": pr_url,
                "stage": "gate1_review",
                "note": "PE worker not hired yet (Wave 0b); baton parked",
            },
            artefact_refs=list(artefact_refs or []),
        )
        stored, _created = await self.emit_baton(baton)
        return stored
