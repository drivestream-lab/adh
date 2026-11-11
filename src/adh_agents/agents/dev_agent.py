"""DevAgent — engg think → board seed (not coder)."""

from __future__ import annotations

import asyncio
import re

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.collaboration.human_replies import REVISE_ENGG, normalize_reply
from src.adh_agents.programmes.dev.programme import DevEnggProgramme
from src.adh_agents.programmes.pm.lead_tokens import extract_initiative
from src.adh_agents.runtime.autonomy import AutonomyPolicy
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.runtime.presence import PresenceService
from src.adh_agents.runtime.room_resolve import listen_rooms_for_tenants, resolve_tenant_for_room
from src.adh_agents.runtime.work_models import AWAITING_AUTHORIZATION, AWAITING_JUDGMENT
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import DevAgentSettings
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import MessageKind, MessageRead

_HIRE = re.compile(r"(?i)\b(?:hire\s+engg|hire\s+dev|@adh\.dev|engg\s+think)\b")
_BATON_TYPE = "dev.engg_think"


class DevAgent(BaseHermesAgent):
    role_id = "adh.dev"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        batons: RedisBatonStore,
        tenants: TenantRegistryService,
        orchestrator: Orchestrator,
        programme: DevEnggProgramme,
        work_store: AgentWorkStore,
        presence: PresenceService,
        autonomy: AutonomyPolicy,
    ) -> None:
        settings = DevAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings, presence=presence)
        self._tenants = tenants
        self._orchestrator = orchestrator
        self._programme = programme
        self._work_store = work_store
        self._autonomy = autonomy
        self._lead = HermesSettings.get_instance().lead_handle
        self._bg: set[asyncio.Task[None]] = set()

    async def initialize(self) -> None:
        await super().initialize()
        self._orchestrator.bind_role(self.role_id)
        self._orchestrator.set_programme_runner(self._programme)
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
        self.logger.info("DevAgent listening", rooms=rooms)

    async def _god_resume_open_gates(self) -> None:
        if not self._autonomy.is_god:
            return
        for tenant in self._tenants.active():
            try:
                active = await self._work_store.list_active(tenant.slug, self.role_id)
            except Exception:
                self.logger.exception("god Dev resume list_active failed", tenant=tenant.slug)
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
                        purpose=(brief.purpose or brief.node_id or "dev-gate"),
                    )
                    if not ok:
                        self.logger.warning(
                            "god Dev resume skipped",
                            reason=reason,
                            initiative=session.initiative,
                        )
                        continue
                    await self._programme.after_judgment(tenant, room, session, token)
                except Exception:
                    self.logger.exception(
                        "god Dev resume failed",
                        tenant=tenant.slug,
                        initiative=session.initiative,
                    )

    async def _catch_up_pending_batons(self) -> None:
        ttl = int(self._agent_settings.baton_ttl_seconds)
        for tenant in self._tenants.active():
            await self._batons.reclaim_stale(tenant=tenant.slug, max_age_seconds=ttl)
            pending = await self._batons.list_pending_for(
                tenant=tenant.slug, to_role=self.role_id, baton_type=_BATON_TYPE
            )
            for baton in pending:
                await self._programme.handle_baton(baton, room=baton.ops_room or tenant.ops_room)

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        tenant = await resolve_tenant_for_room(self._tenants, self._buzz, room)
        if tenant is None:
            return
        payload = message.payload or {}
        if (
            payload.get("status") == "baton_emitted"
            and payload.get("baton_type") == _BATON_TYPE
            and payload.get("idempotency_key")
        ):
            baton = await self._batons.get(
                tenant=str(payload.get("tenant") or tenant.slug),
                idempotency_key=str(payload["idempotency_key"]),
            )
            if baton is not None:
                await self._programme.handle_baton(baton, room=room)
                return

        if message.kind != MessageKind.MESSAGE or (message.identity_handle or "") != self._lead:
            return

        body = (message.body or "").strip()
        if not body:
            return

        # Post-board revise engg
        if normalize_reply(body, [REVISE_ENGG]) == REVISE_ENGG or REVISE_ENGG in body.lower():
            init = extract_initiative(body, tenant.init_prefix) or ""
            active = await self._work_store.list_active(tenant.slug, self.role_id)
            session = None
            if init:
                session = await self._work_store.load(tenant.slug, self.role_id, init.upper())
            if session is None:
                for s in active:
                    if (s.slots.get("board_seeded") or "").lower() in {"1", "true", "yes"}:
                        session = s
                        break
            if session is not None:
                await self.ack_received(
                    room,
                    lead_body=body,
                    source_message_id=str(message.id) if message.id else None,
                )
                await self._programme.handle_revise_engg(tenant, room, session)
                return

        # Lead hire / explicit engg think
        if _HIRE.search(body):
            init = extract_initiative(body, tenant.init_prefix)
            if not init:
                await self.broadcast_progress(
                    room,
                    "Hire engg needs an INIT id (e.g. `hire engg INIT-007`).",
                    payload={"status": "hire_need_init"},
                )
                return
            await self.ack_received(
                room,
                lead_body=body,
                source_message_id=str(message.id) if message.id else None,
            )
            pr_url = _extract_pr_url(body)
            await self._programme.start_for_initiative(
                tenant, room, initiative=init, prd_pr_url=pr_url
            )
            return

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


def _extract_pr_url(body: str) -> str:
    m = re.search(r"https://github\.com/[^\s]+/pull/\d+", body or "")
    return m.group(0) if m else ""
