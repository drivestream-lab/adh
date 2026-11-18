"""CoderAgent — claim ``coder.wave`` batons; walk wave-* (human + god)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from injector import inject

from src.adh_agents.base import BaseHermesAgent
from src.adh_agents.baton.models import Baton
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.programmes.coder.programme import CoderWaveProgramme
from src.adh_agents.programmes.coder.repo_lease import CoderRepoLeaseStore
from src.adh_agents.programmes.coder.roles import coder_role_prefix, is_coder_role
from src.adh_agents.programmes.dev.coder_handoff import DevCoderHandoff
from src.adh_agents.programmes.dev.impact_repos import resolve_repo_root
from src.adh_agents.programmes.dev.paths import implementation_plan_path
from src.adh_agents.programmes.pm.lead_tokens import extract_initiative
from src.adh_agents.programmes.pm.traj_coach import TrajCoachProgramme
from src.adh_agents.runtime.autonomy import AutonomyPolicy
from src.adh_agents.runtime.lead_commands import LeadCommand, match_lead_command
from src.adh_agents.runtime.orchestrator import Orchestrator
from src.adh_agents.runtime.presence import PresenceService
from src.adh_agents.runtime.room_resolve import (
    engg_collaboration_room,
    listen_rooms_for_role,
    resolve_tenant_for_room,
)
from src.adh_agents.runtime.work_models import (
    AWAITING_AUTHORIZATION,
    AWAITING_JUDGMENT,
    AWAITING_NONE,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import CoderAgentSettings
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import MessageKind, MessageRead

_BATON_TYPE = "coder.wave"
# Mirror Dev stalled-skill resume — Coder YAML skill nodes only (not forge actions).
_CODER_SKILL_STAGES = frozenset({"pre-implement", "loop-spec", "learning-extract", "ground-spec"})


class CoderAgent(BaseHermesAgent):
    role_id = "adh.coder"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        batons: RedisBatonStore,
        tenants: TenantRegistryService,
        orchestrator: Orchestrator,
        programme: CoderWaveProgramme,
        leases: CoderRepoLeaseStore,
        coder_handoff: DevCoderHandoff,
        traj_coach: TrajCoachProgramme,
        work_store: AgentWorkStore,
        presence: PresenceService,
        autonomy: AutonomyPolicy,
    ) -> None:
        settings = CoderAgentSettings.get_instance()
        super().__init__(buzz=buzz, batons=batons, settings=settings, presence=presence)
        self._tenants = tenants
        self._orchestrator = orchestrator
        self._programme = programme
        self._leases = leases
        self._coder_handoff = coder_handoff
        self._traj_coach = traj_coach
        self._work_store = work_store
        self._autonomy = autonomy
        self._coder_settings = settings
        self._lead = HermesSettings.get_instance().lead_handle
        self._bg: set[asyncio.Task[None]] = set()

    async def initialize(self) -> None:
        await super().initialize()
        self._orchestrator.bind_role(self.role_id)
        self._orchestrator.set_programme_runner(self._programme)
        for tenant in self._tenants.active():
            await self.ensure_hub_member(tenant.ops_room)
        rooms = await listen_rooms_for_role(self._buzz, self._tenants, self.role_id)
        await self.start_ops_listeners(rooms)
        await self._catch_up_pending_batons()
        task = asyncio.create_task(self._god_resume_open_gates())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        self.start_listen_refresh_loop(
            lambda: listen_rooms_for_role(self._buzz, self._tenants, self.role_id),
            interval_seconds=15.0,
            on_added=self._on_rooms_added,
        )
        catch = asyncio.create_task(self._pending_baton_loop())
        self._bg.add(catch)
        catch.add_done_callback(self._bg.discard)
        self.logger.info(
            "CoderAgent listening",
            rooms=rooms,
            max_parallel_coders=self._coder_settings.max_parallel_coders,
        )

    async def _on_rooms_added(self, added: list[str]) -> None:
        del added
        await self._catch_up_pending_batons()

    async def _pending_baton_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(12.0)
                await self._catch_up_pending_batons()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("Coder pending baton loop failed")

    async def _god_resume_open_gates(self) -> None:
        """God resume — same shape as DevAgent._god_resume_open_gates."""
        if not self._autonomy.is_god:
            return
        for tenant in self._tenants.active():
            try:
                active = await self._work_store.list_active(tenant.slug, self.role_id)
            except Exception:
                self.logger.exception("god Coder resume list_active failed", tenant=tenant.slug)
                continue
            for session in active:
                room = session.room or tenant.ops_room
                # Navigator may set awaiting before GateOpener posts a brief —
                # re-enter the spine so the coach opens (then god auto-takes).
                if (
                    session.awaiting in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION)
                    and session.open_brief is None
                ):
                    try:
                        await self._programme.start_programme(tenant, room, session)
                    except Exception:
                        self.logger.exception(
                            "god Coder spine re-open failed",
                            tenant=tenant.slug,
                            initiative=session.slots.get("initiative") or session.initiative,
                        )
                    continue
                # Skill-stage stall left awaiting=none — re-enter so a fixed
                # verifier / re-run can progress (Dev stalled-skill pattern).
                stage = (session.stage or "").strip()
                if (
                    session.awaiting == AWAITING_NONE
                    and session.open_brief is None
                    and stage in _CODER_SKILL_STAGES
                    and not any(
                        k.startswith(f"skill:{stage}:") and v == "ok"
                        for k, v in (session.slots or {}).items()
                    )
                ):
                    try:
                        await self._programme.start_programme(tenant, room, session)
                    except Exception:
                        self.logger.exception(
                            "god Coder stalled-skill resume failed",
                            tenant=tenant.slug,
                            initiative=session.slots.get("initiative") or session.initiative,
                            stage=stage,
                        )
                    continue
                if session.awaiting not in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION):
                    continue
                brief = session.open_brief
                if brief is None:
                    continue
                token = self._autonomy.resolve_token(brief)
                if token is None:
                    continue
                try:
                    ok, reason = await self._autonomy.record_take(
                        tenant=tenant.slug,
                        initiative=(
                            session.slots.get("initiative")
                            or session.initiative
                            or session.work_id
                            or ""
                        ).strip(),
                        purpose=(brief.purpose or brief.node_id or "coder-gate"),
                    )
                    if not ok:
                        self.logger.warning(
                            "god Coder resume skipped",
                            reason=reason,
                            initiative=session.slots.get("initiative") or session.initiative,
                        )
                        continue
                    await self._programme.after_judgment(tenant, room, session, token)
                except Exception:
                    self.logger.exception(
                        "god Coder resume failed",
                        tenant=tenant.slug,
                        initiative=session.slots.get("initiative") or session.initiative,
                    )

    async def _catch_up_pending_batons(self) -> None:
        ttl = int(self._agent_settings.baton_ttl_seconds)
        for tenant in self._tenants.active():
            await self._batons.reclaim_stale(tenant=tenant.slug, max_age_seconds=ttl)
            pending = await self._batons.list_pending_for(
                tenant=tenant.slug,
                to_role_prefix=coder_role_prefix(),
                baton_type=_BATON_TYPE,
            )
            # Verify→Coder returns must bypass clip_ready: the wave repo already
            # holds a lease from hire / loop-spec, and clip_ready skips any held
            # key — otherwise verify_accepted stays pending forever.
            returns: list[Baton] = []
            repos: list[str] = []
            by_repo: dict[str, Baton] = {}
            for baton in pending:
                payload = baton.payload or {}
                stage = str(payload.get("stage") or "").strip()
                repo = str(payload.get("repo") or "").strip()
                if stage in {"verify_accepted", "verify_collab"}:
                    returns.append(baton)
                    continue
                if not repo or repo in by_repo:
                    continue
                by_repo[repo] = baton
                repos.append(repo)
            for baton in returns:
                await self._programme.handle_baton(baton, room=baton.ops_room or tenant.ops_room)
            allowed = await self._leases.clip_ready(
                repos,
                tenant=tenant.slug,
                max_parallel=int(self._coder_settings.max_parallel_coders),
            )
            for repo in allowed:
                claimed = by_repo[repo]
                await self._programme.handle_baton(
                    claimed, room=claimed.ops_room or tenant.ops_room
                )

    async def handle_ops_message(self, room: str, message: MessageRead) -> None:
        tenant = await resolve_tenant_for_room(self._tenants, self._buzz, room)
        if tenant is None:
            return
        payload = message.payload or {}
        status = str(payload.get("status") or "")
        if status == "baton_emitted" and payload.get("baton_type") == _BATON_TYPE:
            key = payload.get("idempotency_key")
            if key:
                baton = await self._batons.get(
                    tenant=str(payload.get("tenant") or tenant.slug),
                    idempotency_key=str(key),
                )
                if baton is not None and is_coder_role(baton.to_role):
                    await self._programme.handle_baton(baton, room=room)
                    return
        if status == "coder_handoff":
            await self._catch_up_pending_batons()
            return

        if message.kind != MessageKind.MESSAGE or (message.identity_handle or "") != self._lead:
            return

        body = (message.body or "").strip()
        if not body:
            return

        cmd = match_lead_command(
            body, allowed=[LeadCommand.HIRE_CODER, LeadCommand.RESUME, LeadCommand.TRAJ]
        )
        if cmd == LeadCommand.TRAJ:
            init = extract_initiative(body, tenant.init_prefix)
            if not init:
                active = await self._work_store.list_active(tenant.slug, self.role_id)
                for s in active:
                    if (s.room or "") == room:
                        init = (s.slots.get("initiative") or s.initiative or "").strip()
                        if init:
                            break
            await self._traj_coach.handle_lead(
                tenant, room, body=body, task_id=(init or "").upper() or None
            )
            return

        if cmd == LeadCommand.HIRE_CODER:
            init = extract_initiative(body, tenant.init_prefix)
            if not init:
                await self.broadcast_progress(
                    room,
                    "Hire coder needs an INIT id (e.g. `hire coder INIT-REALWORLD-001`).",
                    payload={"status": "hire_coder_need_init"},
                )
                return
            await self.ack_received(
                room,
                lead_body=body,
                source_message_id=str(message.id) if message.id else None,
            )
            await self._hire_coder(tenant, room, initiative=init.upper())
            return

        if cmd == LeadCommand.RESUME:
            await self._orchestrator.handle_lead_message(tenant, room, message)
            return

        # Open gates (incl. dynamic wave-pickup tokens) — same path as Dev/PM.
        active = await self._work_store.list_active(tenant.slug, self.role_id)
        open_gates = [
            s
            for s in active
            if s.awaiting in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION)
            and s.open_brief is not None
            and (not s.room or s.room == room)
        ]
        if open_gates:
            await self._orchestrator.handle_lead_message(tenant, room, message)
            return

    async def _hire_coder(self, tenant, room: str, *, initiative: str) -> None:
        """C4 resume — re-emit ready-repo batons for a board-seeded INIT (e.g. 001)."""
        init = initiative.strip().upper()
        engg = await engg_collaboration_room(self._buzz, tenant, initiative=init, fallback=room)
        plan_rel = implementation_plan_path(init)
        # Prefer product repo checkout of the plan when present under workspace.
        plan_path: Path | str = plan_rel
        ws = self._tenants.workspace_root()
        for name in (
            sorted(p.name for p in Path(ws).iterdir() if p.is_dir()) if Path(ws).is_dir() else []
        ):
            candidate = resolve_repo_root(ws, name)
            if candidate is not None and (candidate / plan_rel).is_file():
                plan_path = candidate / plan_rel
                break
        issued = await self._coder_handoff.handoff_to_coder(
            tenant,
            initiative=init,
            engg_room=engg,
            plan_path=plan_path,
            board_seed_marker=f"hire_coder:{init}",
            source_room=room,
        )
        if not issued:
            await self.broadcast_progress(
                room,
                f"Hire coder **{init}** — no batons emitted (parse/ready-set failed).",
                payload={"status": "hire_coder_empty", "initiative": init},
            )
            return
        await self._catch_up_pending_batons()
        await self.broadcast_progress(
            room,
            f"Hire coder **{init}** — {len(issued)} ready-repo baton(s) claimed/queued.",
            payload={
                "status": "hire_coder_done",
                "initiative": init,
                "baton_count": len(issued),
            },
        )
