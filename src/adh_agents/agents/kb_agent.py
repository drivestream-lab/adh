"""KbAgent — OKF knowledge/ head patches."""

from __future__ import annotations

import asyncio

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.kb.enrich import KbEnrichProgramme
from src.adh_agents.runtime.autonomy import AutonomyPolicy
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.runtime.presence import PresenceService
from src.adh_agents.runtime.room_resolve import listen_rooms_for_tenants, resolve_tenant_for_room
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
        presence: PresenceService,
        autonomy: AutonomyPolicy,
    ) -> None:
        settings = KbAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings, presence=presence)
        self._tenants = tenants
        self._orchestrator = orchestrator
        self._enrich = enrich
        self._work_store = work_store
        self._autonomy = autonomy
        self._lead = HermesSettings.get_instance().lead_handle
        self._bg: set[asyncio.Task[None]] = set()

    async def initialize(self) -> None:
        await super().initialize()
        self._orchestrator.bind_role(self.role_id)
        self._orchestrator.set_programme_runner(self._enrich)
        for tenant in self._tenants.active():
            await self.ensure_hub_member(tenant.ops_room)
        rooms = await listen_rooms_for_tenants(self._buzz, self._tenants)
        await self.start_ops_listeners(rooms)
        await self._catch_up_pending_batons()
        task = asyncio.create_task(self._god_resume_open_gates())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        self.start_listen_refresh_loop(
            lambda: listen_rooms_for_tenants(self._buzz, self._tenants),
            interval_seconds=15.0,
        )
        self.logger.info("KbAgent listening", rooms=rooms)

    async def _god_resume_open_gates(self) -> None:
        """God: auto-play Hermes recommend on any open KB gate left from a prior halt."""
        if not self._autonomy.is_god:
            return
        for tenant in self._tenants.active():
            try:
                active = await self._work_store.list_active(tenant.slug, self.role_id)
            except Exception:
                self.logger.exception("god KB resume list_active failed", tenant=tenant.slug)
                continue
            for session in active:
                if session.awaiting not in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION):
                    continue
                brief = session.open_brief
                if brief is None:
                    continue
                token = self._autonomy.resolve_token(brief)
                if token is None:
                    continue
                room = session.room or tenant.ops_room
                try:
                    ok, reason = await self._autonomy.record_take(
                        tenant=tenant.slug,
                        initiative=(session.initiative or session.work_id or "").strip(),
                        purpose=(brief.purpose or brief.node_id or "kb-gate"),
                    )
                    if not ok:
                        self.logger.warning(
                            "god KB resume skipped",
                            reason=reason,
                            initiative=session.initiative,
                        )
                        continue
                    self.logger.info(
                        "god KB resume playing recommend",
                        initiative=session.initiative,
                        token=token,
                        purpose=brief.purpose,
                    )
                    await self._enrich.after_judgment(tenant, room, session, token)
                except Exception:
                    self.logger.exception(
                        "god KB resume failed",
                        tenant=tenant.slug,
                        initiative=session.initiative,
                    )

    async def _catch_up_pending_batons(self) -> None:
        ttl = int(self._agent_settings.baton_ttl_seconds)
        for tenant in self._tenants.active():
            await self._batons.reclaim_stale(tenant=tenant.slug, max_age_seconds=ttl)
            pending = await self._batons.list_pending_for(
                tenant=tenant.slug, to_role=self.role_id, baton_type="kb.enrich"
            )
            for baton in pending:
                await self._enrich.handle_baton(baton, room=baton.ops_room or tenant.ops_room)

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        tenant = await resolve_tenant_for_room(self._tenants, self._buzz, room)
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
