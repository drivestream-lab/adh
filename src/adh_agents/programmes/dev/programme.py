"""Dev engg-think programme — catalogue spine → board seed."""

from __future__ import annotations

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.human_replies import (
    ACCEPT_DEPS,
    ACCEPT_TDD_ADR,
    ANOTHER_ROUND,
    AUTHORIZE_BOARD,
    CODING_READY,
    HOLD,
    NEED_ANOTHER_ROUND,
    REVISE_ENGG,
    normalize_reply,
)
from src.adh_agents.execution.dispatch_service import HermesDispatchService
from src.adh_agents.programmes.dev.board_seed import (
    board_seed_preconditions,
    mark_board_seeded,
)
from src.adh_agents.programmes.dev.debate import DebateResult, run_dev_debate
from src.adh_agents.programmes.dev.deps import (
    deps_has_visible_dag,
    ensure_engg_deps_stub,
)
from src.adh_agents.programmes.dev.entry import resolve_dev_entry
from src.adh_agents.programmes.dev.gates import (
    board_authorize_brief,
    board_authorize_coach,
    coding_ready_brief,
    coding_ready_coach,
    deps_acceptance_brief,
    deps_acceptance_coach,
    tdd_adr_brief,
    tdd_adr_coach,
)
from src.adh_agents.programmes.dev.paths import (
    engg_deps_path,
    feasibility_report_path,
    implementation_plan_path,
    technical_review_path,
)
from src.adh_agents.programmes.dev.revise import apply_revise_engg_slots, is_post_board
from src.adh_agents.programmes.dev.verification_plan import (
    ensure_verification_plan_stub,
    verification_plan_has_coverage_table,
)
from src.adh_agents.programmes.pm.validation_report import impact_map_path
from src.adh_agents.runtime.gate_opener import GateOpener
from src.adh_agents.runtime.room_resolve import engg_collaboration_room
from src.adh_agents.runtime.work_models import (
    AWAITING_AUTHORIZATION,
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    PROGRAMME_DEV,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import DevAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.infra_services.litellm_service import LiteLLMService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import EventType, TaskEventCreate, TaskEventKind, TaskState
from src.models.tenant_models import TenantContext

_STAGE_ENTRY = "entry"
_STAGE_FEAS = "initiative-feasibility"
_STAGE_TECH = "spec-technical-review"
_STAGE_DEPS = "deps-acceptance"
_STAGE_TDD = "tdd-adr-acceptance"
_STAGE_PLAN = "spec-implementation-plan"
_STAGE_CODING = "coding-readiness"
_STAGE_BOARD = "board-tickets-action"
_STAGE_DONE = "board-seeded"


class DevEnggProgramme(BaseBusinessService):
    programme_id = PROGRAMME_DEV
    role_id = "adh.dev"

    @inject
    def __init__(
        self,
        store: AgentWorkStore,
        batons: RedisBatonStore,
        poster: HermesBuzzPoster,
        briefs: HermesBriefService,
        workspace: PmWorkspaceService,
        dispatch: HermesDispatchService,
        gates: GateOpener,
        buzz: BuzzService,
        tenants: TenantRegistryService,
        litellm: LiteLLMService,
    ) -> None:
        super().__init__()
        self._store = store
        self._batons = batons
        self._poster = poster
        self._briefs = briefs
        self._workspace = workspace
        self._dispatch = dispatch
        self._gates = gates
        self._buzz = buzz
        self._tenants = tenants
        self._litellm = litellm
        self._settings = DevAgentSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        await self._run_spine(tenant, room, session)

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        init = (work_id or "").strip().upper()
        session = await self._store.load(tenant.slug, self.role_id, init)
        if session is None:
            await self._poster.post_status(
                room,
                f"Dev resume: no session for `{init}`.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        await self._run_spine(tenant, room, session)

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        del tenant
        return []

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        stage = (session.stage or "").strip()
        allowed = list(session.open_brief.reply_tokens) if session.open_brief else []
        matched = normalize_reply(token, allowed) or (token or "").strip().lower()
        if matched in {HOLD, "park"} or "hold" in matched:
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._poster.post_status(
                room,
                f"Holding Dev engg-think for {session.initiative}.",
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
            return

        if stage == _STAGE_DEPS:
            await self._on_deps_token(tenant, room, session, matched)
            return
        if stage == _STAGE_TDD:
            await self._on_tdd_token(tenant, room, session, matched)
            return
        if stage == _STAGE_CODING:
            await self._on_coding_token(tenant, room, session, matched)
            return
        if stage == _STAGE_BOARD:
            await self._on_board_token(tenant, room, session, matched)
            return

        await self._run_spine(tenant, room, session)

    async def handle_baton(self, baton: Baton, *, room: str) -> Rollup:
        ttl = int(self._settings.baton_ttl_seconds)
        claimed = await self._batons.claim(baton, claimant=self.role_id, ttl=ttl)
        if not claimed:
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="claim failed",
                correlation_id=baton.correlation_id,
                error="claim_failed",
            )
        await self._batons.mark_running(baton, ttl=ttl)
        tenant = self._tenants.by_slug(baton.tenant)
        if tenant is None:
            await self._batons.mark_done(baton, ttl=ttl, error="unknown_tenant")
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="unknown tenant",
                correlation_id=baton.correlation_id,
                error="unknown_tenant",
            )
        init = (baton.initiative or "").strip().upper()
        payload = baton.payload or {}
        pr_url = str(payload.get("prd_pr_url") or payload.get("pr_url") or "").strip()
        collab = (baton.ops_room or "").strip() or await engg_collaboration_room(
            self._buzz,
            tenant,
            initiative=init,
            fallback=room or tenant.ops_room,
        )
        if not collab.startswith("engg-"):
            collab = await engg_collaboration_room(
                self._buzz, tenant, initiative=init, fallback=collab
            )
        session = AgentWorkSession(
            role_id=self.role_id,
            tenant_slug=tenant.slug,
            room=collab,
            work_id=init,
            initiative=init,
            programme=PROGRAMME_DEV,
            stage=_STAGE_ENTRY,
            slots={
                "prd_pr_url": pr_url,
                "pr_url": pr_url,
                "baton_key": baton.idempotency_key,
            },
        )
        await self._store.save(session)
        await self._poster.post_status(
            collab,
            f"Dev claimed `dev.engg_think` for **{init}** — starting engg-think spine.",
            EventType.PROGRESS,
            {
                "status": "dev_claimed",
                "initiative": init,
                "collab": True,
                "baton_type": "dev.engg_think",
            },
            identity_handle=self.role_id,
        )
        try:
            await self._run_spine(tenant, collab, session)
            done = await self._batons.mark_done(baton, ttl=ttl)
            return Rollup(
                baton_id=done.id,
                role=self.role_id,
                status=BatonStatus.DONE,
                summary="dev engg-think bound",
                correlation_id=baton.correlation_id,
            )
        except Exception as exc:
            await self._batons.mark_done(baton, ttl=ttl, error=str(exc))
            await self._poster.post_status(
                collab,
                f"Dev engg-think failed for **{init}**: {exc}",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="dev engg-think failed",
                correlation_id=baton.correlation_id,
                error=str(exc),
            )

    async def start_for_initiative(
        self,
        tenant: TenantContext,
        room: str,
        *,
        initiative: str,
        prd_pr_url: str = "",
    ) -> None:
        init = initiative.strip().upper()
        collab = await engg_collaboration_room(
            self._buzz, tenant, initiative=init, fallback=room or tenant.ops_room
        )
        if (room or "").startswith("engg-"):
            collab = room
        session = await self._store.load(tenant.slug, self.role_id, init)
        if session is None:
            session = AgentWorkSession(
                role_id=self.role_id,
                tenant_slug=tenant.slug,
                room=collab,
                work_id=init,
                initiative=init,
                programme=PROGRAMME_DEV,
                stage=_STAGE_ENTRY,
                slots={},
            )
        if prd_pr_url:
            session.slots["prd_pr_url"] = prd_pr_url
            session.slots.setdefault("pr_url", prd_pr_url)
        session.room = collab
        await self._store.save(session)
        await self._run_spine(tenant, collab, session)

    async def handle_revise_engg(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        if not is_post_board(session.slots):
            await self._poster.post_status(
                room,
                (
                    f"**{session.initiative}** is not board-seeded yet — "
                    "continue current gates (or `hold`)."
                ),
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
            return
        session.slots = apply_revise_engg_slots(session.slots)
        session.stage = session.slots.get("reopen_stage") or _STAGE_DEPS
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        await self._store.save(session)
        await self._poster.post_status(
            room,
            (
                f"**Revise engg** for **{session.initiative}** — prior board seed "
                "marked superseded; reopening deps-acceptance (no silent rewrite)."
            ),
            EventType.PROGRESS,
            {"status": "revise_engg", "initiative": session.initiative},
            identity_handle=self.role_id,
        )
        await self._append_event(
            session,
            kind=TaskEventKind.STATE,
            purpose="revise-engg",
            payload={"reopen": session.stage},
        )
        await self._run_spine(tenant, room, session)

    # ── spine ──────────────────────────────────────────────────────────

    async def _run_spine(self, tenant: TenantContext, room: str, session: AgentWorkSession) -> None:
        if session.awaiting in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION):
            return
        init = (session.initiative or session.work_id or "").strip().upper()
        entry, stall = resolve_dev_entry(
            self._workspace,
            tenant,
            initiative=init,
            prd_pr_url=session.slots.get("prd_pr_url") or session.slots.get("pr_url") or "",
            slots=session.slots,
        )
        if stall or entry is None:
            await self._poster.post_status(
                room,
                stall or "Dev entry failed.",
                EventType.STALL,
                {"status": "dev_entry_blocked", "initiative": init},
                identity_handle=self.role_id,
            )
            return

        session.initiative = entry.initiative
        session.work_id = entry.initiative
        session.slots["prd_pr_url"] = entry.prd_pr_url
        session.programme = PROGRAMME_DEV
        session.room = room
        await self._set_task_running(session)

        stage = (session.stage or _STAGE_ENTRY).strip()
        if stage in {_STAGE_ENTRY, _STAGE_FEAS}:
            await self._run_feasibility(tenant, room, session)
            stage = session.stage or ""
        if stage == _STAGE_TECH:
            await self._run_technical_review(tenant, room, session)
            stage = session.stage or ""
        if stage == _STAGE_DEPS:
            await self._open_deps_gate(tenant, room, session)
            return
        if stage == _STAGE_TDD:
            await self._open_tdd_gate(tenant, room, session)
            return
        if stage == _STAGE_PLAN:
            await self._run_plan(tenant, room, session)
            stage = session.stage or ""
        if stage == _STAGE_CODING:
            await self._open_coding_gate(tenant, room, session)
            return
        if stage == _STAGE_BOARD:
            await self._open_board_gate(tenant, room, session)
            return
        if stage == _STAGE_DONE:
            await self._poster.post_status(
                room,
                (
                    f"**{init}** board already seeded. "
                    f"Reply `{REVISE_ENGG}` to reopen think (supersede + re-seed)."
                ),
                EventType.DONE,
                identity_handle=self.role_id,
            )

    async def _run_feasibility(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.initiative or ""
        session.stage = _STAGE_FEAS
        await self._store.save(session)
        await self._poster.post_status(
            room,
            f"Dev running `initiative-feasibility` for **{init}**…",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )
        try:
            result = await self._dispatch.run_catalog_skill(
                tenant,
                "initiative-feasibility",
                init,
                on_progress=self._progress_cb(room),
            )
            if not result.ok:
                await self._poster.post_status(
                    room,
                    f"Feasibility skill failed for **{init}** (exit {result.exit_code}).",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return
        except Exception as exc:
            # Skill may be missing on some profiles — continue with existing artefacts.
            await self._poster.post_status(
                room,
                f"Feasibility dispatch note for **{init}**: {exc} — continuing if artefacts exist.",
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
        session.slots["feasibility_path"] = feasibility_report_path(init)
        session.stage = _STAGE_TECH
        await self._store.save(session)

    async def _run_technical_review(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.initiative or ""
        session.stage = _STAGE_TECH
        await self._store.save(session)
        await self._poster.post_status(
            room,
            f"Dev running `spec-technical-review` for **{init}**…",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )
        try:
            result = await self._dispatch.run_catalog_skill(
                tenant,
                "spec-technical-review",
                init,
                on_progress=self._progress_cb(room),
            )
            if not result.ok:
                await self._poster.post_status(
                    room,
                    f"Technical review skill failed for **{init}** (exit {result.exit_code}).",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Technical review dispatch note for **{init}**: {exc} — continuing to deps.",
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
        session.slots["technical_review_path"] = technical_review_path(init)
        session.stage = _STAGE_DEPS
        await self._store.save(session)

    async def _open_deps_gate(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.initiative or ""
        impact = self._workspace.read_local(tenant, impact_map_path(init)) or ""
        path = ensure_engg_deps_stub(
            self._workspace, tenant, initiative=init, impact_map_body=impact
        )
        body = self._workspace.read_local(tenant, path) or ""
        if not deps_has_visible_dag(body):
            await self._poster.post_status(
                room,
                (
                    f"Engg-Deps at `{path}` has no visible repo tiers yet — "
                    f"edit it, then reply `{ANOTHER_ROUND}` or wait for coach."
                ),
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
        session.stage = _STAGE_DEPS
        session.slots["engg_deps_path"] = path
        debate = await self._debate_hop(
            purpose="deps-acceptance",
            initiative=init,
            context=body or impact,
            reply_tokens=[ACCEPT_DEPS, ANOTHER_ROUND, HOLD],
            session=session,
        )
        brief = deps_acceptance_brief(self._briefs, initiative=init, artefact=path, debate=debate)
        god = await self._gates.open(
            session,
            brief=brief,
            awaiting=AWAITING_JUDGMENT,
            coach=deps_acceptance_coach(initiative=init, artefact=path, debate=debate),
        )
        if god:
            await self.after_judgment(tenant, room, session, god)

    async def _open_tdd_gate(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.initiative or ""
        artefact = session.slots.get("technical_review_path") or technical_review_path(init)
        session.stage = _STAGE_TDD
        ctx = self._workspace.read_local(tenant, artefact) or artefact
        debate = await self._debate_hop(
            purpose="tdd-adr-acceptance",
            initiative=init,
            context=ctx,
            reply_tokens=[ACCEPT_TDD_ADR, ANOTHER_ROUND, HOLD],
            session=session,
        )
        brief = tdd_adr_brief(self._briefs, initiative=init, artefact=artefact, debate=debate)
        god = await self._gates.open(
            session,
            brief=brief,
            awaiting=AWAITING_JUDGMENT,
            coach=tdd_adr_coach(initiative=init, artefact=artefact, debate=debate),
        )
        if god:
            await self.after_judgment(tenant, room, session, god)

    async def _run_plan(self, tenant: TenantContext, room: str, session: AgentWorkSession) -> None:
        init = session.initiative or ""
        session.stage = _STAGE_PLAN
        await self._store.save(session)
        await self._poster.post_status(
            room,
            f"Dev running `spec-implementation-plan` for **{init}**…",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )
        try:
            result = await self._dispatch.run_catalog_skill(
                tenant,
                "spec-implementation-plan",
                init,
                on_progress=self._progress_cb(room),
            )
            if not result.ok:
                await self._poster.post_status(
                    room,
                    f"Implementation plan skill failed for **{init}** (exit {result.exit_code}).",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Plan dispatch note for **{init}**: {exc} — ensuring verification plan stub.",
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
        plan = implementation_plan_path(init)
        vplan = ensure_verification_plan_stub(self._workspace, tenant, initiative=init)
        session.slots["implementation_plan_path"] = plan
        session.slots["verification_plan_path"] = vplan
        session.stage = _STAGE_CODING
        await self._store.save(session)

    async def _open_coding_gate(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.initiative or ""
        plan = session.slots.get("implementation_plan_path") or implementation_plan_path(init)
        vplan = session.slots.get("verification_plan_path") or ensure_verification_plan_stub(
            self._workspace, tenant, initiative=init
        )
        body = self._workspace.read_local(tenant, vplan) or ""
        if not verification_plan_has_coverage_table(body):
            await self._poster.post_status(
                room,
                (
                    f"Verification plan at `{vplan}` needs a coverage table "
                    "(Dev plans proofs; CI/human run them)."
                ),
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        session.stage = _STAGE_CODING
        plan_body = self._workspace.read_local(tenant, plan) or ""
        debate = await self._debate_hop(
            purpose="coding-readiness",
            initiative=init,
            context=f"{plan_body}\n\n{body}",
            reply_tokens=[CODING_READY, ANOTHER_ROUND, HOLD],
            session=session,
        )
        brief = coding_ready_brief(
            self._briefs,
            initiative=init,
            plan_path=plan,
            verification_path=vplan,
            debate=debate,
        )
        god = await self._gates.open(
            session,
            brief=brief,
            awaiting=AWAITING_JUDGMENT,
            coach=coding_ready_coach(
                initiative=init,
                plan_path=plan,
                verification_path=vplan,
                debate=debate,
            ),
        )
        if god:
            await self.after_judgment(tenant, room, session, god)

    async def _open_board_gate(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.initiative or ""
        check = board_seed_preconditions(session.slots)
        if not check.ok:
            await self._poster.post_status(
                room,
                check.reason,
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        session.stage = _STAGE_BOARD
        debate = await self._debate_hop(
            purpose="board-tickets-action",
            initiative=init,
            context=f"coding_ready={session.slots.get('coding_ready_accepted')}",
            reply_tokens=[AUTHORIZE_BOARD, HOLD],
            session=session,
        )
        brief = board_authorize_brief(self._briefs, initiative=init, debate=debate)
        god = await self._gates.open(
            session,
            brief=brief,
            awaiting=AWAITING_AUTHORIZATION,
            coach=board_authorize_coach(initiative=init, debate=debate),
        )
        if god:
            await self.after_judgment(tenant, room, session, god)

    # ── gate tokens ────────────────────────────────────────────────────

    async def _on_deps_token(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        if token in {ANOTHER_ROUND, NEED_ANOTHER_ROUND} or "round" in token:
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            session.stage = _STAGE_DEPS
            await self._store.save(session)
            await self._open_deps_gate(tenant, room, session)
            return
        if ACCEPT_DEPS in token or token == ACCEPT_DEPS or "accept deps" in token:
            path = session.slots.get("engg_deps_path") or engg_deps_path(session.initiative or "")
            body = self._workspace.read_local(tenant, path) or ""
            if not deps_has_visible_dag(body):
                await self._poster.post_status(
                    room,
                    f"Cannot accept deps — `{path}` still has no concrete repo tiers.",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return
            session.slots["deps_accepted"] = "true"
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            session.stage = _STAGE_TDD
            await self._store.save(session)
            await self._open_tdd_gate(tenant, room, session)
            return
        await self._poster.post_status(
            room,
            f"Unrecognized deps reply `{token}`.",
            EventType.STALL,
            identity_handle=self.role_id,
        )

    async def _on_tdd_token(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        if token in {ANOTHER_ROUND, NEED_ANOTHER_ROUND} or "round" in token:
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            session.stage = _STAGE_TECH
            await self._store.save(session)
            await self._run_spine(tenant, room, session)
            return
        if ACCEPT_TDD_ADR in token or "accept tdd" in token or "accept adr" in token:
            session.slots["tdd_adr_accepted"] = "true"
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            session.stage = _STAGE_PLAN
            await self._store.save(session)
            await self._run_spine(tenant, room, session)
            return
        await self._poster.post_status(
            room,
            f"Unrecognized tdd-adr reply `{token}`.",
            EventType.STALL,
            identity_handle=self.role_id,
        )

    async def _on_coding_token(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        if token in {ANOTHER_ROUND, NEED_ANOTHER_ROUND} or "round" in token:
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            session.stage = _STAGE_PLAN
            await self._store.save(session)
            await self._run_spine(tenant, room, session)
            return
        if CODING_READY in token or "coding ready" in token or "coding-ready" in token:
            session.slots["coding_ready_accepted"] = "true"
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            session.stage = _STAGE_BOARD
            await self._store.save(session)
            await self._open_board_gate(tenant, room, session)
            return
        await self._poster.post_status(
            room,
            f"Unrecognized coding-ready reply `{token}`.",
            EventType.STALL,
            identity_handle=self.role_id,
        )

    async def _on_board_token(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        if AUTHORIZE_BOARD not in token and "board" not in token and "seed" not in token:
            await self._poster.post_status(
                room,
                f"Unrecognized board reply `{token}`.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        check = board_seed_preconditions(session.slots)
        if not check.ok:
            await self._poster.post_status(
                room, check.reason, EventType.STALL, identity_handle=self.role_id
            )
            return
        init = session.initiative or ""
        await self._poster.post_status(
            room,
            f"Dev seeding board tickets for **{init}** via `create-board-tickets`…",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )
        try:
            result = await self._dispatch.run_catalog_skill(
                tenant,
                "create-board-tickets",
                init,
                on_progress=self._progress_cb(room),
            )
            ok = bool(result.ok)
            summary = f"exit={result.exit_code}"
        except Exception as exc:
            ok = False
            summary = str(exc)
        if not ok:
            await self._poster.post_status(
                room,
                (
                    f"Board seed skill did not complete for **{init}** ({summary}). "
                    "Gate stays — fix artefacts and authorize again."
                ),
                EventType.STALL,
                identity_handle=self.role_id,
            )
            # Re-open authorize
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._open_board_gate(tenant, room, session)
            return

        session.slots = mark_board_seeded(session.slots, marker=f"create-board-tickets:{init}")
        session.stage = _STAGE_DONE
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        await self._store.save(session)
        await self._append_event(
            session,
            kind=TaskEventKind.LAND,
            purpose="board-seed",
            payload={"initiative": init},
        )
        await self._poster.post_status(
            room,
            (
                f"**{init}** board tickets seeded — Dev v1 fence complete. "
                f"Coder hire is later. Reply `{REVISE_ENGG}` to reopen think."
            ),
            EventType.DONE,
            {"status": "board_seeded", "initiative": init},
            identity_handle=self.role_id,
        )

    # ── helpers ────────────────────────────────────────────────────────

    async def _debate_hop(
        self,
        *,
        purpose: str,
        initiative: str,
        context: str,
        reply_tokens: list[str],
        session: AgentWorkSession,
    ) -> DebateResult:
        await self._poster.post_status(
            session.room,
            f"Dev debating `{purpose}` for **{initiative}** (cap {self._settings.max_think_runs})…",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )
        debate = await run_dev_debate(
            self._litellm,
            purpose=purpose,
            initiative=initiative,
            context=context,
            reply_tokens=reply_tokens,
            max_runs=int(self._settings.max_think_runs),
        )
        session.slots[f"debate:{purpose}:passes"] = str(debate.passes)
        session.slots[f"debate:{purpose}:converged_at"] = str(debate.converged_at_pass)
        session.slots[f"debate:{purpose}:hit_ceiling"] = "1" if debate.hit_ceiling else "0"
        await self._store.save(session)
        note = (
            f"Debate `{purpose}` → recommend `{debate.recommend}` "
            f"at pass {debate.converged_at_pass}/{self._settings.max_think_runs}"
            + (" **(hit ceiling)**" if debate.hit_ceiling else "")
        )
        await self._poster.post_status(
            session.room,
            note,
            EventType.PROGRESS,
            {
                "status": "dev_debate",
                "purpose": purpose,
                "converged_at_pass": debate.converged_at_pass,
                "hit_ceiling": debate.hit_ceiling,
            },
            identity_handle=self.role_id,
        )
        return debate

    def _progress_cb(self, room: str):
        async def _on_progress(msg: str) -> None:
            try:
                await self._poster.post_status(
                    room,
                    msg,
                    EventType.PROGRESS,
                    identity_handle=self.role_id,
                )
            except Exception:
                self.logger.exception("dev progress post failed")

        return _on_progress

    async def _set_task_running(self, session: AgentWorkSession) -> None:
        task_id = (session.initiative or session.work_id or "").strip()
        if not task_id:
            return
        try:
            await self._buzz.set_task_state(
                session.tenant_slug,
                task_id,
                TaskState.RUNNING,
                role_id=self.role_id,
            )
        except Exception:
            self.logger.exception("dev set_task_state failed", initiative=task_id)

    async def _append_event(
        self,
        session: AgentWorkSession,
        *,
        kind: TaskEventKind,
        purpose: str,
        payload: dict | None = None,
    ) -> None:
        task_id = (session.initiative or session.work_id or "").strip()
        if not task_id:
            return
        try:
            await self._buzz.append_task_event(
                TaskEventCreate(
                    tenant_slug=session.tenant_slug,
                    task_id=task_id,
                    kind=kind,
                    role_id=self.role_id,
                    purpose=purpose,
                    payload=payload or {},
                ),
            )
        except Exception:
            self.logger.exception("dev append_task_event failed", initiative=task_id)
