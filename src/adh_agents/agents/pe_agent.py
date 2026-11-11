"""PEAgent — product brief / clarification rally; embeds Orchestrator."""

from __future__ import annotations

import re

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.pe.engg_handoff import PeEnggHandoff
from src.adh_agents.programmes.pe.review import PeReviewProgramme
from src.adh_agents.programmes.pm.lead_tokens import extract_initiative
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.runtime.presence import PresenceService
from src.adh_agents.runtime.room_resolve import listen_rooms_for_tenants, resolve_tenant_for_room
from src.adh_agents.runtime.work_models import AWAITING_AUTHORIZATION, AWAITING_JUDGMENT
from src.adh_agents.settings import PeAgentSettings
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import MessageKind, MessageRead
from src.models.tenant_models import TenantContext

_GATE1_VERBS = frozenset({"gate1", "review"})
# Lead escape hatches only — happy path is agent settle after pe.pm_answers (U6).
_GATE1_FORK_TOKENS = frozenset(
    {"attest", "approve", "new_round", "round_again", "hold", "park", "await_pm"}
)
_ENGG_GO = re.compile(r"(?i)\bengg\s+go\b")


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
        engg_handoff: PeEnggHandoff,
        presence: PresenceService,
    ) -> None:
        settings = PeAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings, presence=presence)
        self._tenants = tenants
        self._orchestrator = orchestrator
        self._pe = pe
        self._engg_handoff = engg_handoff
        self._lead = HermesSettings.get_instance().lead_handle

    async def initialize(self) -> None:
        await super().initialize()
        self._orchestrator.bind_role(self.role_id)
        self._orchestrator.set_programme_runner(self._pe)
        for tenant in self._tenants.active():
            await self.ensure_hub_member(tenant.ops_room)
        rooms = await listen_rooms_for_tenants(self._buzz, self._tenants)
        await self.start_ops_listeners(rooms)
        await self._catch_up_pending_batons()
        self.start_listen_refresh_loop(
            lambda: listen_rooms_for_tenants(self._buzz, self._tenants),
            interval_seconds=15.0,
        )
        self.logger.info("PEAgent listening", rooms=rooms)

    async def _catch_up_pending_batons(self) -> None:
        """Claim pe.review / pe.pm_answers batons parked before this worker was online."""
        ttl = int(self._agent_settings.baton_ttl_seconds)
        for tenant in self._tenants.active():
            await self._batons.reclaim_stale(tenant=tenant.slug, max_age_seconds=ttl)
            for baton_type in ("pe.review", "pe.pm_answers"):
                pending = await self._batons.list_pending_for(
                    tenant=tenant.slug, to_role=self.role_id, baton_type=baton_type
                )
                for baton in pending:
                    room = baton.ops_room or tenant.ops_room
                    if baton.type == "pe.pm_answers":
                        await self._pe.handle_pm_answers(baton, room=room)
                    else:
                        await self._pe.handle_baton(baton, room=room)

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        tenant = await resolve_tenant_for_room(self._tenants, self._buzz, room)
        if tenant is None:
            return
        payload = message.payload or {}
        baton_type = str(payload.get("baton_type") or "")
        if (
            payload.get("status") == "baton_emitted"
            and baton_type in {"pe.review", "pe.pm_answers"}
            and payload.get("idempotency_key")
        ):
            baton = await self._batons.get(
                tenant=str(payload.get("tenant") or tenant.slug),
                idempotency_key=str(payload["idempotency_key"]),
            )
            if baton is not None:
                if baton_type == "pe.pm_answers":
                    await self._pe.handle_pm_answers(baton, room=room)
                else:
                    await self._pe.handle_baton(baton, room=room)
                return
        if message.kind == MessageKind.MESSAGE and (message.identity_handle or "") == self._lead:
            body = (message.body or "").strip()
            if _ENGG_GO.search(body):
                init = extract_initiative(body, tenant.init_prefix)
                if not init:
                    await self.broadcast_progress(
                        room,
                        "engg go needs an INIT id (e.g. `engg go INIT-REALWORLD-001 https://…/pull/5`).",
                        payload={"status": "engg_go_need_init"},
                    )
                    return
                await self.ack_received(
                    room,
                    lead_body=body,
                    source_message_id=str(message.id) if message.id else None,
                )
                pr_url = _extract_github_pr_url(body) or await self._lookup_pr_url(
                    tenant.slug, init
                )
                await self._engg_handoff.handoff_to_dev(
                    tenant,
                    initiative=init,
                    prd_pr_url=pr_url,
                    source_room=room,
                )
                return
            gate1 = _parse_gate1_command(body, tenant)
            if gate1 is not None:
                await self.ack_received(
                    room,
                    lead_body=body,
                    source_message_id=str(message.id) if message.id else None,
                )
                init, pr_url = gate1
                if not pr_url:
                    pr_url = await self._lookup_pr_url(tenant.slug, init)
                await self._pe.start_gate1(tenant, room, initiative=init, pr_url=pr_url)
                return
            if await self._try_gate1_fork(tenant, room, body, message=message):
                return
            # U2: PE stays silent unless open human gate or explicit resume.
            # Orchestrator acks when it consumes.
            lowered = body.lower()
            if "resume" in lowered:
                await self._orchestrator.handle_lead_message(tenant, room, message)
                return
            active = await self._pe.list_active(tenant.slug)
            open_gates = [
                s
                for s in active
                if s.awaiting in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION)
                and s.open_brief is not None
            ]
            if open_gates:
                await self._orchestrator.handle_lead_message(tenant, room, message)

    async def _try_gate1_fork(
        self,
        tenant: TenantContext,
        room: str,
        body: str,
        *,
        message: MessageRead | None = None,
    ) -> bool:
        """Lead escape: attest / need another round / park (happy path is agent settle)."""
        lowered = (body or "").strip().lower()
        if lowered.startswith("need another round"):
            token = "need another round"
        else:
            token = lowered.split()[0] if lowered else ""
            if token not in _GATE1_FORK_TOKENS:
                return False
        active = await self._pe.list_active(tenant.slug)
        candidates = [
            s
            for s in active
            if s.stage in {"gate1_await_pm", "gate1_questions", "gate1_review", "gate1_settled"}
        ]
        if not candidates:
            return False
        session = candidates[0]
        if len(candidates) > 1:
            mentioned = extract_initiative(body, tenant.init_prefix)
            if mentioned:
                matched = [
                    s for s in candidates if (s.initiative or "").upper() == mentioned.upper()
                ]
                if len(matched) == 1:
                    session = matched[0]
                else:
                    return False
            else:
                return False
        await self.ack_received(
            room,
            lead_body=body,
            source_message_id=str(message.id) if message and message.id else None,
        )
        await self._pe.after_judgment(tenant, room, session, token)
        return True

    async def _lookup_pr_url(self, tenant_slug: str, initiative: str) -> str:
        """Reuse pr_url from a prior pe.review baton when Lead omits it."""
        rows = await self._batons.list_for_tenant(tenant=tenant_slug, baton_type="pe.review")
        for baton in rows:
            if (baton.initiative or "").upper() != initiative.upper():
                continue
            url = str((baton.payload or {}).get("pr_url") or "")
            if url:
                return url
        return ""


def _parse_gate1_command(body: str, tenant: TenantContext) -> tuple[str, str] | None:
    """Lead shorthand: ``gate1 INIT-…`` / ``pe review INIT-…`` [optional PR URL]."""
    parts = body.split()
    if not parts:
        return None
    idx = 0
    if parts[0].lower() == "pe":
        idx = 1
    if idx >= len(parts) or parts[idx].lower() not in _GATE1_VERBS:
        return None
    remainder = " ".join(parts[idx + 1 :])
    initiative = extract_initiative(remainder, tenant.init_prefix)
    if not initiative:
        return None
    return initiative.upper(), _extract_github_pr_url(remainder)


def _extract_github_pr_url(text: str) -> str:
    for token in text.split():
        cleaned = token.strip(".,);]")
        if cleaned.startswith("https://github.com/") and "/pull/" in cleaned:
            return cleaned
    return ""
