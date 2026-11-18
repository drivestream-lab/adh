"""Coder wave programme — YAML walker from wave-in-progress through signoff."""

from __future__ import annotations

from pathlib import Path

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.catalogue.navigator import HermesNavigatorService
from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.human_replies import (
    ANOTHER_ROUND,
    ENTER_CLOSEOUT,
    HOLD,
    MERGE_WAVE_PR,
    WAVE_ACCEPTED,
    normalize_reply,
)
from src.adh_agents.execution.dispatch_service import HermesDispatchService
from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.coder.dirty import (
    assert_clean_worktree,
    discard_worktree_changes,
    list_dirty_relative_paths,
    sync_clean_head_ref,
    sync_clean_integration,
)
from src.exceptions.app_exceptions import ValidationError
from src.adh_agents.programmes.coder.forge_ops import (
    commit_workspace,
    land_wave_pr,
    move_wave_board_status,
    open_wave_draft_pr,
    pick_wave_issue_url,
    project_wave_accepted,
)
from src.adh_agents.programmes.coder.board_tickets import (
    load_manifest,
    resolve_board_tickets,
)
from src.adh_agents.programmes.coder.gates import (
    closeout_enter_brief,
    closeout_enter_coach,
    wave_pickup_brief,
    wave_pickup_coach,
    wave_signoff_brief,
    wave_signoff_coach,
)
from src.adh_agents.programmes.coder.paths import wave_branch, wave_execution_report_path
from src.adh_agents.programmes.coder.ready_set import ready_wave_ids_for_repo
from src.adh_agents.programmes.coder.repo_lease import CoderRepoLeaseStore
from src.adh_agents.programmes.coder.roles import coder_role_for_repo, is_coder_role
from src.adh_agents.programmes.coder.verify_handoff import CoderVerifyHandoff
from src.adh_agents.programmes.dev.impact_repos import resolve_repo_root
from src.adh_agents.programmes.dev.paths import implementation_plan_path
from src.adh_agents.programmes.pm.validation_report import impact_map_path
from src.adh_agents.runtime.agentic_decide import decide_catalogue_outcome, decide_reply_token
from src.adh_agents.runtime.gate_opener import GateOpener
from src.adh_agents.runtime.work_models import (
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    PROGRAMME_CODER,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import CoderAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.configs.hermes_settings import HermesSettings
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.pm_workspace_service import PmWorkspaceService, prd_path
from src.infra_services.prompt_service import PromptService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.infra_services.workflow_catalogue_service import WorkflowCatalogueService
from src.models.buzz_models import EventType, TaskEventCreate, TaskEventKind
from src.models.tenant_models import TenantContext

_BATON_TYPE = "coder.wave"
_WAVE_PICKUP = "wave-pickup"
_WAVE_ENTRY = "wave-in-progress-action"
_WAVE_CHAIN = frozenset(
    {
        "wave-in-progress-action",
        "pre-implement",
        "loop-spec",
        "wave-pr-action",
        "wave-acceptance",
        "wave-awaiting-closeout",
        "learning-extract",
        "ground-spec",
        "wave-done-action",
        "wave-signoff",
        "wave-complete",
    }
)
_SKILL_NODES = frozenset({"pre-implement", "loop-spec", "learning-extract", "ground-spec"})


class CoderWaveProgramme(BaseBusinessService):
    """Lease → YAML wave-* walker. Human gates always open a brief; god plays recommend."""

    programme_id = PROGRAMME_CODER
    role_id = "adh.coder"

    @inject
    def __init__(
        self,
        store: AgentWorkStore,
        batons: RedisBatonStore,
        poster: HermesBuzzPoster,
        buzz: BuzzService,
        tenants: TenantRegistryService,
        leases: CoderRepoLeaseStore,
        forge: ForgeActionService,
        workspace: PmWorkspaceService,
        github: GitHubAppService,
        dispatch: HermesDispatchService,
        catalogue: WorkflowCatalogueService,
        navigator: HermesNavigatorService,
        prompts: PromptService,
        briefs: HermesBriefService,
        gates: GateOpener,
        verify_handoff: CoderVerifyHandoff,
    ) -> None:
        super().__init__()
        self._store = store
        self._batons = batons
        self._poster = poster
        self._buzz = buzz
        self._tenants = tenants
        self._leases = leases
        self._forge = forge
        self._workspace = workspace
        self._github = github
        self._dispatch = dispatch
        self._catalogue = catalogue
        self._navigator = navigator
        self._prompts = prompts
        self._briefs = briefs
        self._gates = gates
        self._verify_handoff = verify_handoff
        self._settings = CoderAgentSettings.get_instance()

    def _voice(self, session: AgentWorkSession) -> str:
        """Buzz identity for this wave — repo-scoped swarm unit (ADR 0005 / C.13)."""
        handle = (session.slots.get("coder_handle") or "").strip()
        if is_coder_role(handle) and handle != self.role_id:
            return handle
        repo = (session.slots.get("repo") or "").strip()
        if repo:
            try:
                return coder_role_for_repo(repo)
            except ValueError:
                pass
        return self.role_id

    async def _traj(
        self,
        session: AgentWorkSession,
        *,
        purpose: str,
        token: str = "",
        kind: TaskEventKind = TaskEventKind.STATE,
    ) -> None:
        """Append run trajectory (Postgres ``buzz_task_events``) — Lead ``traj`` SSOT."""
        init = (
            (session.slots.get("initiative") or session.initiative or session.work_id or "")
            .strip()
            .upper()
        )
        if not init:
            return
        try:
            await self._buzz.append_task_event(
                TaskEventCreate(
                    tenant_slug=session.tenant_slug,
                    task_id=init.split(":", 1)[0],
                    kind=kind,
                    role_id=self._voice(session),
                    purpose=(purpose or session.stage or "coder")[:128],
                    token=(token or session.stage or "")[:256],
                    payload={
                        "repo": session.slots.get("repo") or "",
                        "wave": session.slots.get("active_wave") or "",
                        "stage": session.stage or "",
                        "work_id": session.work_id or "",
                    },
                )
            )
        except Exception:
            self.logger.exception(
                "coder trajectory write failed",
                initiative=init,
                purpose=purpose,
                stage=session.stage,
            )

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        if (session.stage or "").strip() == _WAVE_PICKUP:
            await self._open_wave_pickup_gate(tenant, room, session)
            return
        await self._continue_wave(tenant, room, session)

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        session = await self._store.load(tenant.slug, self.role_id, work_id)
        if session is None:
            await self._poster.post_status(
                room,
                f"Coder resume: no session for `{work_id}`.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        if (session.stage or "").strip() == _WAVE_PICKUP:
            await self._open_wave_pickup_gate(tenant, room, session)
            return
        await self._continue_wave(tenant, room, session)

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        del tenant
        return []

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        stage = (session.stage or "").strip()
        allowed = list(session.open_brief.reply_tokens) if session.open_brief else []
        matched = normalize_reply(token, allowed) or (token or "").strip()
        matched_l = matched.lower()
        init = session.slots.get("initiative") or session.initiative or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""

        if matched_l in {HOLD, "park"} or matched_l == "hold":
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._poster.post_status(
                room,
                f"Coder parked **{init}** `{wave or 'wave-pickup'}` on `{repo}`.",
                EventType.PROGRESS,
                identity_handle=self._voice(session),
            )
            return

        if stage == _WAVE_PICKUP:
            pick = matched if matched in allowed else matched.upper()
            ready = [w for w in (session.slots.get("ready_waves") or "").split(",") if w.strip()]
            if pick not in ready and pick.upper() not in {w.upper() for w in ready}:
                await self._poster.post_status(
                    room,
                    (
                        f"Coder ignored `{token}` at wave-pickup — "
                        f"reply with one of: {', '.join(ready) or HOLD}."
                    ),
                    EventType.PROGRESS,
                    identity_handle=self._voice(session),
                )
                return
            # Preserve case from ready list.
            for w in ready:
                if w.upper() == pick.upper():
                    pick = w
                    break
            session.slots["active_wave"] = pick
            session.slots["wave_ids"] = ",".join(ready)
            session.open_brief = None
            session.awaiting = AWAITING_NONE
            session.stage = _WAVE_ENTRY
            await self._store.save(session)
            await self._poster.post_status(
                room,
                f"Coder picking up wave `{pick}` for **{init}** on `{repo}`.",
                EventType.PROGRESS,
                {"status": "coder_wave_picked", "wave": pick, "repo": repo},
                identity_handle=self._voice(session),
            )
            await self._continue_wave(tenant, room, session)
            return

        if stage == "wave-acceptance":
            if matched == ANOTHER_ROUND or "another" in matched:
                session.open_brief = None
                session.awaiting = AWAITING_NONE
                self._navigator.advance(session, "findings")
                await self._store.save(session)
                await self._continue_wave(tenant, room, session)
                return
            if matched == WAVE_ACCEPTED or matched == "wave-accepted":
                session.open_brief = None
                session.awaiting = AWAITING_NONE
                self._navigator.advance(session, "pass")
                await self._store.save(session)
                await self._continue_wave(tenant, room, session)
                return

        if stage == "wave-awaiting-closeout":
            if matched == ENTER_CLOSEOUT or "closeout" in matched:
                session.open_brief = None
                session.awaiting = AWAITING_NONE
                session.stage = "learning-extract"
                await self._store.save(session)
                await self._continue_wave(tenant, room, session)
                return
            if matched == ANOTHER_ROUND:
                session.open_brief = None
                session.awaiting = AWAITING_NONE
                session.stage = "loop-spec"
                await self._store.save(session)
                await self._continue_wave(tenant, room, session)
                return

        if stage == "wave-signoff":
            if matched == MERGE_WAVE_PR or "merge" in matched:
                ok = await self._land_wave(tenant, room, session)
                if not ok:
                    return
                session.open_brief = None
                session.awaiting = AWAITING_NONE
                self._navigator.advance(session, "pass")
                await self._store.save(session)
                await self._on_wave_complete(tenant, room, session)
                return

        await self._poster.post_status(
            room,
            f"Coder ignored token `{token}` at `{stage}` — reply with a listed token.",
            EventType.PROGRESS,
            identity_handle=self._voice(session),
        )

    async def handle_baton(self, baton: Baton, *, room: str) -> Rollup:
        ttl = int(self._settings.baton_ttl_seconds)
        if (baton.type or "").strip() != _BATON_TYPE or not is_coder_role(baton.to_role):
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="unexpected baton",
                correlation_id=baton.correlation_id,
                error="wrong_baton",
            )

        tenant = self._tenants.by_slug(baton.tenant)
        if tenant is None:
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
        repo = str(payload.get("repo") or "").strip()
        stage_hint = str(payload.get("stage") or "").strip()
        raw_waves = payload.get("wave_ids")
        wave_ids: list[str] = [str(x) for x in raw_waves] if isinstance(raw_waves, list) else []
        if not wave_ids and payload.get("wave_id"):
            wave_ids = [str(payload.get("wave_id"))]
        raw_urls = payload.get("board_issue_urls")
        board_urls: list[str] = [str(x) for x in raw_urls] if isinstance(raw_urls, list) else []
        collab = (baton.ops_room or "").strip() or room or tenant.ops_room
        if not repo:
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="missing repo",
                correlation_id=baton.correlation_id,
                error="missing_repo",
            )

        # Verify → Coder return batons (collaboration / acceptance).
        if stage_hint in {"verify_collab", "verify_accepted"}:
            if not await self._batons.claim(baton, claimant=self.role_id, ttl=ttl):
                return Rollup(
                    baton_id=baton.id,
                    role=self.role_id,
                    status=BatonStatus.FAILED,
                    summary="claim failed",
                    correlation_id=baton.correlation_id,
                    error="claim_failed",
                )
            await self._batons.mark_running(baton, ttl=ttl)
            work_id = f"{init}:{repo}"
            session = await self._store.load(tenant.slug, self.role_id, work_id)
            if session is None:
                await self._poster.post_status(
                    collab,
                    (
                        f"Coder refuse Verify return `{stage_hint}` — no work session "
                        f"`{work_id}` (hire/wave must exist before Verify→Coder)."
                    ),
                    EventType.STALL,
                    {"status": "coder_missing_session", "work_id": work_id},
                    identity_handle=coder_role_for_repo(repo),
                )
                done = await self._batons.mark_done(baton, ttl=ttl, error="missing_session")
                return Rollup(
                    baton_id=done.id,
                    role=self.role_id,
                    status=BatonStatus.FAILED,
                    summary=f"coder_missing_session:{repo}",
                    correlation_id=baton.correlation_id,
                    error="missing_session",
                )
            if not (session.slots.get("coder_handle") or "").strip():
                session.slots["coder_handle"] = (
                    baton.to_role if is_coder_role(baton.to_role) else coder_role_for_repo(repo)
                )
            voice = self._voice(session)
            if stage_hint == "verify_collab":
                session.slots["verify_findings"] = str(payload.get("findings") or "")
                session.slots["verify_pending"] = ""
                session.slots["collab_round"] = str(payload.get("collab_round") or "2")
                session.stage = "loop-spec"
                session.awaiting = AWAITING_NONE
                session.open_brief = None
                await self._store.save(session)
                await self._traj(session, purpose="verify_collab", token="loop-spec")
                await self._poster.post_status(
                    collab,
                    (
                        f"Coder collaboration from Verify for **{init}** "
                        f"`{session.slots.get('active_wave')}` — findings applied → loop-spec."
                    ),
                    EventType.PROGRESS,
                    {
                        "status": "coder_verify_collab",
                        "findings": session.slots.get("verify_findings"),
                    },
                    identity_handle=voice,
                )
                await self._continue_wave(tenant, collab, session)
            else:
                session.slots["verify_pending"] = ""
                session.slots["verify_accepted"] = "true"
                session.stage = "wave-awaiting-closeout"
                session.awaiting = AWAITING_NONE
                session.open_brief = None
                if payload.get("pr_url"):
                    session.slots["wave_pr_url"] = str(payload.get("pr_url"))
                if payload.get("pr_number"):
                    session.slots["wave_pr_number"] = str(payload.get("pr_number"))
                # Phase-1 ingress: project wave-accepted on tip before Pass-2
                # (learning-extract fail-closes without the label).
                pr_n = int(session.slots.get("wave_pr_number") or "0")
                if pr_n > 0:
                    try:
                        await project_wave_accepted(
                            github=self._github,
                            workspace=self._workspace,
                            repo=repo,
                            pr_number=pr_n,
                        )
                        session.slots["wave_accepted_label"] = "true"
                        await self._poster.post_status(
                            collab,
                            (
                                f"Coder projected `wave-accepted` on PR #{pr_n} "
                                f"for **{init}** `{session.slots.get('active_wave')}`."
                            ),
                            EventType.PROGRESS,
                            {"status": "coder_wave_accepted_label", "pr_number": str(pr_n)},
                            identity_handle=voice,
                        )
                    except Exception as exc:
                        await self._poster.post_status(
                            collab,
                            (
                                f"Coder refuse Pass-2 — could not label PR #{pr_n} "
                                f"`wave-accepted`: {exc}"
                            ),
                            EventType.STALL,
                            {"status": "coder_wave_accepted_label_failed"},
                            identity_handle=voice,
                        )
                        done = await self._batons.mark_done(
                            baton, ttl=ttl, error="wave_accepted_label_failed"
                        )
                        await self._store.save(session)
                        return Rollup(
                            baton_id=done.id,
                            role=self.role_id,
                            status=BatonStatus.FAILED,
                            summary=f"wave_accepted_label_failed:{repo}",
                            correlation_id=baton.correlation_id,
                            error="wave_accepted_label_failed",
                        )
                await self._store.save(session)
                await self._traj(session, purpose="verify_accepted", token="wave-awaiting-closeout")
                await self._continue_wave(tenant, collab, session)
            done = await self._batons.mark_done(baton, ttl=ttl)
            return Rollup(
                baton_id=done.id,
                role=self.role_id,
                status=BatonStatus.DONE,
                summary=f"coder_{stage_hint}:{repo}",
                correlation_id=baton.correlation_id,
            )

        lease = await self._leases.try_acquire(
            tenant=tenant.slug, repo=repo, holder=self.role_id, ttl_seconds=ttl
        )
        if not lease.acquired:
            await self._poster.post_status(
                collab,
                (
                    f"Coder deferred `{repo}` for **{init}** — lease held by "
                    f"`{lease.holder or 'another'}` (cap={self._settings.max_parallel_coders})."
                ),
                EventType.PROGRESS,
                {"status": "coder_lease_deferred", "repo": repo, "initiative": init},
                identity_handle=coder_role_for_repo(repo),
            )
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.PENDING,
                summary=f"lease_deferred:{repo}",
                correlation_id=baton.correlation_id,
                error="lease_held",
            )

        if not await self._batons.claim(baton, claimant=self.role_id, ttl=ttl):
            await self._leases.release(tenant=tenant.slug, repo=repo, holder=self.role_id)
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="claim failed",
                correlation_id=baton.correlation_id,
                error="claim_failed",
            )
        await self._batons.mark_running(baton, ttl=ttl)

        plan_ref = ""
        for ref in baton.artefact_refs or []:
            if str(ref).strip():
                plan_ref = str(ref).strip()
                break
        if not plan_ref:
            plan_ref = str(implementation_plan_path(init))

        session = AgentWorkSession(
            role_id=self.role_id,
            tenant_slug=tenant.slug,
            room=collab,
            work_id=f"{init}:{repo}",
            initiative=init,
            programme=PROGRAMME_CODER,
            stage=_WAVE_PICKUP,
            awaiting=AWAITING_NONE,
            slots={
                "initiative": init,
                "repo": repo,
                "wave_ids": ",".join(wave_ids),
                "active_wave": "",
                "coder_handle": (
                    baton.to_role if is_coder_role(baton.to_role) else coder_role_for_repo(repo)
                ),
                "board_seed_marker": str(payload.get("board_seed_marker") or ""),
                "board_issue_urls": " ".join(board_urls),
                "plan_path": plan_ref,
                "coder_spine": "c2_leased",
                "lease_key": lease.key,
                "baton_idempotency_key": baton.idempotency_key or "",
            },
        )
        await self._store.save(session)
        await self._traj(session, purpose="coder_leased", token=_WAVE_PICKUP)
        await self._poster.post_status(
            collab,
            (
                f"Coder leased `{repo}` for **{init}** "
                f"(candidate waves={','.join(wave_ids) or 'n/a'}) — "
                "mapping board tickets then opening wave-pickup gate."
            ),
            EventType.PROGRESS,
            {"status": "coder_leased", "initiative": init, "repo": repo},
            identity_handle=self._voice(session),
        )
        await self._open_wave_pickup_gate(tenant, collab, session)
        done = await self._batons.mark_done(baton, ttl=ttl)
        return Rollup(
            baton_id=done.id,
            role=self.role_id,
            status=BatonStatus.DONE,
            summary=f"coder_pickup:{repo}:{session.stage}",
            correlation_id=baton.correlation_id,
            artefact_refs=list(baton.artefact_refs or []),
        )

    # ── Wave pickup (Hermes + GateOpener — same shape as Dev) ──────────

    def _plan_path_for(self, tenant: TenantContext, session: AgentWorkSession) -> Path:
        raw = (session.slots.get("plan_path") or "").strip()
        if raw:
            p = Path(raw)
            if p.is_file():
                return p
        init = (session.slots.get("initiative") or session.initiative or "").strip().upper()
        rel = implementation_plan_path(init)
        ws = self._tenants.workspace_root()
        repo = (session.slots.get("repo") or "").strip()
        if repo:
            root = resolve_repo_root(ws, repo)
            if root is not None and (root / rel).is_file():
                return root / rel
        for name in (
            sorted(p.name for p in Path(ws).iterdir() if p.is_dir()) if Path(ws).is_dir() else []
        ):
            root = resolve_repo_root(ws, name)
            if root is not None and (root / rel).is_file():
                return root / rel
        meta = Path(tenant.meta_root).expanduser() / rel
        if meta.is_file():
            return meta
        return Path(rel)

    async def _open_wave_pickup_gate(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        """Inventory WM waves + board tickets → Hermes recommend → GateOpener."""
        init = (session.slots.get("initiative") or session.initiative or "").strip().upper()
        repo = (session.slots.get("repo") or "").strip()
        plan_path = self._plan_path_for(tenant, session)
        session.slots["plan_path"] = str(plan_path)

        try:
            snap = await resolve_board_tickets(
                github=self._github,
                workspace=self._workspace,
                plan_path=plan_path,
                initiative=init,
                repo_hint=repo or "",
            )
        except Exception as exc:
            await self._poster.post_status(
                room,
                (
                    f"Coder could not map board tickets for **{init}** (`{repo}`): {exc}. "
                    "Reseed board (Dev) or fix GitHub App issues:read, then `hire coder` again."
                ),
                EventType.STALL,
                {"status": "coder_board_map_failed", "initiative": init, "repo": repo},
                identity_handle=self._voice(session),
            )
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            return

        session.slots["board_issue_urls"] = " ".join(snap.issue_urls)
        for wid, url in snap.wave_urls.items():
            session.slots[f"board_url:{wid}"] = url

        try:
            manifest = load_manifest(plan_path)
            ready = list(ready_wave_ids_for_repo(manifest, repo))
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Coder failed to read WorkManifest ready-set for **{init}**: {exc}",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return

        # Prefer ready waves that still have an open board ticket.
        open_ready = [w for w in ready if (snap.wave_urls.get(w) or "") and w in snap.wave_urls]
        # If we know the URL exists, keep it even when issue state is closed —
        # Hermes still sees evidence lines with state.
        if not open_ready:
            open_ready = [w for w in ready if w in snap.wave_urls]
        if not open_ready:
            await self._poster.post_status(
                room,
                (
                    f"Coder found no ready wave with a board ticket for **{init}** on `{repo}`. "
                    f"WM ready={','.join(ready) or 'none'}. " + " | ".join(snap.evidence_lines[:8])
                ),
                EventType.STALL,
                {"status": "coder_no_ready_ticket", "initiative": init, "repo": repo},
                identity_handle=self._voice(session),
            )
            session.slots["ready_waves"] = ",".join(ready)
            await self._store.save(session)
            return

        session.slots["ready_waves"] = ",".join(open_ready)
        evidence = "\n".join(snap.evidence_lines)
        await self._poster.post_status(
            room,
            (
                f"Coder board map for **{init}** / `{repo}`:\n"
                + "\n".join(f"- {line}" for line in snap.evidence_lines)
            ),
            EventType.PROGRESS,
            {
                "status": "coder_board_mapped",
                "initiative": init,
                "repo": repo,
                "issue_urls": list(snap.issue_urls),
                "ready_waves": list(open_ready),
            },
            identity_handle=self._voice(session),
        )

        decided = await decide_reply_token(
            self._prompts,
            role_id=self.role_id,
            purpose=_WAVE_PICKUP,
            initiative=init,
            reply_tokens=list(open_ready) + [HOLD],
            context=(
                f"Repo `{repo}`. Ready waves: {', '.join(open_ready)}. "
                f"Pick the unfinished coding wave a human developer would start next.\n\n"
                f"{evidence}"
            ),
        )
        recommend = str(decided.get("recommend") or open_ready[0]).strip() or open_ready[0]
        bluf = str(decided.get("bluf") or "").strip()
        example = str(decided.get("example") or "").strip()

        session.stage = _WAVE_PICKUP
        await self._store.save(session)
        brief = wave_pickup_brief(
            self._briefs,
            initiative=init,
            repo=repo,
            ready_waves=open_ready,
            recommend=recommend,
            bluf=bluf,
            evidence=evidence,
            example=example,
        )
        god = await self._gates.open(
            session,
            brief=brief,
            awaiting=AWAITING_JUDGMENT,
            coach=wave_pickup_coach(
                initiative=init,
                repo=repo,
                ready_waves=open_ready,
                recommend=recommend,
                bluf=bluf,
                evidence=evidence,
                example=example,
            ),
        )
        if god:
            await self.after_judgment(tenant, room, session, god)

    # ── YAML walker ────────────────────────────────────────────────────

    async def _continue_wave(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        for _ in range(24):
            if session.awaiting != AWAITING_NONE and session.open_brief is not None:
                return
            stage = (session.stage or "").strip()
            if not stage or stage == "wave-complete":
                await self._on_wave_complete(tenant, room, session)
                return
            if stage == _WAVE_PICKUP:
                await self._open_wave_pickup_gate(tenant, room, session)
                return
            if stage not in _WAVE_CHAIN:
                await self._poster.post_status(
                    room,
                    f"Coder stalled — unknown YAML stage `{stage}`.",
                    EventType.STALL,
                    identity_handle=self._voice(session),
                )
                return
            progressed = await self._dispatch_node(tenant, room, session)
            if not progressed:
                return

    async def _dispatch_node(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> bool:
        stage = (session.stage or "").strip()
        try:
            node = self._catalogue.snapshot().node(stage)
        except KeyError:
            await self._poster.post_status(
                room,
                f"Catalogue missing node `{stage}`.",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return False

        if stage in _SKILL_NODES or node.is_skill():
            evidence, ok = await self._run_skill_stage(tenant, room, session, stage)
            if not ok:
                return False
            outcome = await self._decide_outcome(session, stage, evidence, node)
            repo = (session.slots.get("repo") or "").strip()
            skill_key = f"skill:{stage}:{repo}" if repo else ""
            if outcome in {"failed", "blocked"} or node.outcomes.get(outcome) == "workflow-stop":
                # Cursor may exit 0 after writing a blocked Wave-Execution — do not
                # leave skill:* = ok or god stalled-skill resume will skip the retry.
                if skill_key and session.slots.pop(skill_key, None) is not None:
                    await self._store.save(session)
                await self._poster.post_status(
                    room,
                    f"Coder stalled on `{stage}` outcome `{outcome}`.",
                    EventType.STALL,
                    identity_handle=self._voice(session),
                )
                return False
            if skill_key:
                session.slots[skill_key] = "ok"
            # YAML pin: commit_workspace before advancing (same as PM/Dev forge cadence).
            if not await self._apply_commit_workspace(
                tenant, room, session, stage=stage, node=node, outcome=outcome
            ):
                return False
            self._navigator.advance(session, outcome)
            await self._store.save(session)
            await self._traj(session, purpose=f"skill:{stage}", token=f"{outcome}→{session.stage}")
            return True

        if stage == "wave-in-progress-action":
            if not await self._run_board_status(tenant, room, session, status="in_progress"):
                return False
            self._navigator.advance(session, "pass")
            await self._store.save(session)
            await self._traj(session, purpose="wave-in-progress-action", token="in_progress")
            return True

        if stage == "wave-pr-action":
            if not await self._run_wave_pr(tenant, room, session):
                return False
            self._navigator.advance(session, "pass")
            await self._store.save(session)
            await self._traj(session, purpose="wave-pr-action", token="verify.wave")
            # Hand prove to Verify — do not open wave-acceptance GateOpener (1A).
            await self._handoff_to_verify(tenant, room, session)
            return False

        if stage == "wave-done-action":
            if not await self._run_board_status(tenant, room, session, status="done"):
                return False
            self._navigator.advance(session, "pass")
            await self._store.save(session)
            await self._traj(session, purpose="wave-done-action", token="done")
            return True

        if stage == "wave-acceptance":
            # Verify owns prove; if we land here without handoff, re-emit verify.wave.
            if (session.slots.get("verify_pending") or "") == "true":
                await self._poster.post_status(
                    room,
                    "Coder waiting on Verify prove (`verify.wave` pending).",
                    EventType.PROGRESS,
                    {"status": "coder_await_verify"},
                    identity_handle=self._voice(session),
                )
                return False
            await self._handoff_to_verify(tenant, room, session)
            return False

        if stage == "wave-awaiting-closeout":
            await self._open_closeout_enter(tenant, room, session)
            return False

        if stage == "wave-signoff":
            await self._open_wave_signoff(tenant, room, session)
            return False

        await self._poster.post_status(
            room,
            f"Coder unhandled node `{stage}` ({node.type}).",
            EventType.STALL,
            identity_handle=self._voice(session),
        )
        return False

    async def _decide_outcome(
        self, session: AgentWorkSession, stage: str, evidence: str, node: object
    ) -> str:
        outcomes = list(getattr(node, "outcomes", {}) or {})
        return await decide_catalogue_outcome(
            self._prompts,
            role_id=self.role_id,
            node_id=stage,
            initiative=session.slots.get("initiative") or "",
            allowed_outcomes=outcomes,
            evidence=evidence,
            kb_excerpt="",
            template_id="hermes.coder.decide.outcome",
        )

    async def _apply_commit_workspace(
        self,
        tenant: TenantContext,
        room: str,
        session: AgentWorkSession,
        *,
        stage: str,
        node: object,
        outcome: str,
    ) -> bool:
        """Honour YAML ``forge.commit_workspace`` after a skill hop (PM/Dev parity)."""
        forge = getattr(node, "forge", None)
        policy = (getattr(forge, "commit_workspace", None) or "").strip().lower()
        if policy not in {"required", "optional"}:
            return True
        # blocked/failed already returned; still publish when optional+pass-like.
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""
        root = resolve_repo_root(self._tenants.workspace_root(), repo)
        if root is None:
            await self._poster.post_status(
                room,
                f"commit_workspace: missing checkout `{repo}` after `{stage}`.",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return False
        branch = session.slots.get("head_ref") or wave_branch(
            initiative=init, wave_id=wave, repo=repo
        )
        session.slots["head_ref"] = branch
        progress_s = int(HermesSettings.get_instance().progress_seconds)
        await self._poster.post_status(
            room,
            (
                f"Coder YAML `commit_workspace` ({policy}) after `{stage}` "
                f"→ `{repo}`@{branch} (progress every {progress_s}s)…"
            ),
            EventType.PROGRESS,
            {
                "status": "coder_commit_workspace",
                "node": stage,
                "repo": repo,
                "branch": branch,
                "policy": policy,
            },
            identity_handle=self._voice(session),
        )
        try:
            pushed = await commit_workspace(
                github=self._github,
                workspace=self._workspace,
                tenant=tenant,
                repo=repo,
                repo_root=root,
                branch=branch,
                initiative=init,
                stage=stage,
                wave_id=wave,
                required=(policy == "required"),
            )
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Coder `commit_workspace` failed after `{stage}`: {exc}",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return False
        await self._poster.post_status(
            room,
            (
                f"Coder `commit_workspace` after `{stage}` "
                f"({len(pushed)} path(s) → `{branch}`)."
                if pushed
                else f"Coder `commit_workspace` after `{stage}` — nothing dirty (optional)."
            ),
            EventType.PROGRESS,
            {
                "status": "coder_commit_workspace_done",
                "paths": pushed,
                "branch": branch,
                "outcome": outcome,
            },
            identity_handle=self._voice(session),
        )
        session.slots[f"commit:{stage}"] = ",".join(pushed) if pushed else "clean"
        return True

    async def _run_skill_stage(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, stage: str
    ) -> tuple[str, bool]:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""
        ws_root = self._tenants.workspace_root()
        root = resolve_repo_root(ws_root, repo)
        if root is None:
            await self._poster.post_status(
                room,
                f"Missing checkout `{repo}` under `{ws_root}` for `{stage}`.",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return "", False
        try:
            try:
                assert_clean_worktree(root, label=repo)
            except Exception:
                # Forge Contents push (wave-pr / commit_workspace) can leave local
                # copies after remote publish — discard once, then re-assert.
                leftover = list_dirty_relative_paths(root)
                await self._poster.post_status(
                    room,
                    (
                        f"Coder discarding forge leftovers before `{stage}` on `{repo}`: "
                        f"{', '.join(leftover[:8])}{'…' if len(leftover) > 8 else ''}"
                    ),
                    EventType.PROGRESS,
                    {
                        "status": "coder_discard_forge_leftovers",
                        "repo": repo,
                        "stage": stage,
                        "paths": leftover,
                    },
                    identity_handle=self._voice(session),
                )
                discard_worktree_changes(root)
                assert_clean_worktree(root, label=repo)
            base = (tenant.integration_branch or "").strip()
            if not base:
                raise ValidationError(
                    "tenant.integration_branch unset — set governance integration_branch"
                )
            branch = (session.slots.get("head_ref") or "").strip() or wave_branch(
                initiative=init, wave_id=wave, repo=repo
            )
            # Wave skills on head_ref tip (prior commit_workspace), created from
            # tenant.integration_branch when the remote wave head does not exist yet.
            sync_clean_head_ref(root, branch=branch, create_from=base)
            session.slots["head_ref"] = branch
            session.slots["base_ref"] = base
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Coder refuse `{stage}` on `{repo}`: {exc}",
                EventType.STALL,
                {"status": "coder_dirty_or_sync", "repo": repo, "stage": stage},
                identity_handle=self._voice(session),
            )
            return "", False

        prd_abs = str((Path(tenant.meta_root).expanduser() / prd_path(init)).resolve())
        impact_abs = str((Path(tenant.meta_root).expanduser() / impact_map_path(init)).resolve())
        branch = session.slots.get("head_ref") or wave_branch(
            initiative=init, wave_id=wave, repo=repo
        )
        # Same cadence announcement as PM/Dev long skills (Hermes still-working ticks).
        progress_s = int(HermesSettings.get_instance().progress_seconds)
        await self._poster.post_status(
            room,
            (
                f"Coder running YAML skill `{stage}` for **{init}** `{wave}` "
                f"on `{repo}`@{branch} (progress every {progress_s}s)…"
            ),
            EventType.PROGRESS,
            {
                "status": "coder_skill_start",
                "node": stage,
                "repo": repo,
                "branch": branch,
                "progress_seconds": progress_s,
            },
            identity_handle=self._voice(session),
        )
        extra = (
            f"Coder wave `{wave}` on repo `{repo}`. "
            f"Bound head_ref `{branch}` from integration "
            f"`{session.slots['base_ref']}`. "
            f"PRD: {prd_abs}. Impact-Map: {impact_abs}. "
            "Implement only this wave's TASK* serially. "
            "When finished, state clearly whether the skill pass is clean or blocked."
        )
        try:
            result = await self._dispatch.run_skill_node(
                tenant,
                stage,
                init,
                on_progress=self._poster.still_working_callback(
                    room,
                    hop=stage,
                    initiative=init,
                    label=f"`{stage}`/`{repo}`",
                    identity_handle=self._voice(session),
                ),
                workspace=root,
                repo=repo,
                extra_prompt=extra,
                prd_path=prd_abs,
                reports_dir="docs/specification/reports",
            )
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"`{stage}` failed on `{repo}`: {exc}",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return "", False
        if not result.ok:
            await self._poster.post_status(
                room,
                f"`{stage}` exit {result.exit_code} on `{repo}`.",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return (result.output or "")[:8000], False
        # skill:{stage}:{repo}=ok is set only after catalogue outcome advances
        # (not here) so blocked Wave-Execution can be retried by god resume.
        await self._store.save(session)
        return (result.output or "")[:8000], True

    async def _run_board_status(
        self,
        tenant: TenantContext,
        room: str,
        session: AgentWorkSession,
        *,
        status: str,
    ) -> bool:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""
        urls = (session.slots.get("board_issue_urls") or "").split()
        wave_ids = [w for w in (session.slots.get("wave_ids") or "").split(",") if w]
        try:
            wave_index = wave_ids.index(wave) if wave in wave_ids else 0
            issue_url = pick_wave_issue_url(urls, wave_id=wave or "W?", wave_index=wave_index)
            result = await move_wave_board_status(
                forge=self._forge,
                workspace=self._workspace,
                tenant=tenant,
                issue_url=issue_url,
                status=status,
                repo_hint=repo,
            )
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Coder `update_board_status` ({status}) failed for **{init}**: {exc}",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return False
        await self._poster.post_status(
            room,
            (f"Coder board `{wave}` → **{status}** " f"({result.detail or result.url or 'ok'})."),
            EventType.PROGRESS,
            {"status": f"coder_board_{status}", "wave": wave, "repo": repo},
            identity_handle=self._voice(session),
        )
        session.slots[f"board_{status}"] = "true"
        return True

    async def _run_wave_pr(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> bool:
        if not forge_allowed(self.role_id, "open_draft_pr"):
            await self._poster.post_status(
                room,
                "Forge ACL denies open_draft_pr for adh.coder.",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return False
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""
        root = resolve_repo_root(self._tenants.workspace_root(), repo)
        if root is None:
            await self._poster.post_status(
                room,
                f"Missing checkout `{repo}` for wave-pr-action.",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return False
        try:
            assert_clean_worktree(root, label=repo)
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Coder refuse wave-pr-action: {exc}",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return False
        branch = session.slots.get("head_ref") or wave_branch(
            initiative=init, wave_id=wave, repo=repo
        )
        exec_rel = wave_execution_report_path(initiative=init, wave_id=wave)
        push = [p for p in [exec_rel] if (root / p).is_file()]
        try:
            result = await open_wave_draft_pr(
                forge=self._forge,
                github=self._github,
                workspace=self._workspace,
                tenant=tenant,
                repo=repo,
                repo_root=root,
                initiative=init,
                wave_id=wave,
                branch=branch,
                push_paths=push,
            )
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"wave-pr-action failed for `{repo}`: {exc}",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return False
        session.slots["wave_pr_url"] = result.url or ""
        session.slots["wave_pr_number"] = str(result.pr_number or "")
        session.slots["head_ref"] = branch
        await self._poster.post_status(
            room,
            f"Coder opened wave Draft PR for `{wave}` on `{repo}`: {result.url or result.pr_number}",
            EventType.PROGRESS,
            {
                "status": "coder_wave_pr",
                "pr_url": result.url or "",
                "pr_number": str(result.pr_number or ""),
            },
            identity_handle=self._voice(session),
        )
        return True

    async def _land_wave(self, tenant: TenantContext, room: str, session: AgentWorkSession) -> bool:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""
        pr_number = int(session.slots.get("wave_pr_number") or "0")
        if pr_number <= 0:
            await self._poster.post_status(
                room,
                "Coder signoff: missing wave_pr_number — cannot merge.",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return False
        try:
            result = await land_wave_pr(
                forge=self._forge,
                workspace=self._workspace,
                repo=repo,
                pr_number=pr_number,
                initiative=init,
                wave_id=wave,
            )
            root = resolve_repo_root(self._tenants.workspace_root(), repo)
            if root is not None:
                sync_clean_integration(root, branch=(tenant.integration_branch or "").strip())
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Coder wave merge failed: {exc}",
                EventType.STALL,
                identity_handle=self._voice(session),
            )
            return False
        session.slots["wave_merged"] = "true"
        session.slots["wave_merge_sha"] = result.url or ""
        await self._poster.post_status(
            room,
            f"Coder merged wave `{wave}` for **{init}** on `{repo}` ({result.url or 'ok'}).",
            EventType.DONE,
            {"status": "coder_wave_merged", "wave": wave, "repo": repo},
            identity_handle=self._voice(session),
        )
        return True

    async def _handoff_to_verify(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""
        round_n = int(session.slots.get("collab_round") or "1")
        await self._verify_handoff.emit_verify_wave(
            tenant,
            initiative=init,
            engg_room=room,
            repo=repo,
            wave_id=wave,
            pr_url=session.slots.get("wave_pr_url") or "",
            pr_number=session.slots.get("wave_pr_number") or "",
            verify_command=session.slots.get("verify_command") or "make verify",
            compose_dir=session.slots.get("compose_dir") or "",
            coverage_packet=session.slots.get("coverage_packet") or "",
            coder_handle=session.slots.get("coder_handle") or self.role_id,
            round_n=round_n,
        )
        session.slots["verify_pending"] = "true"
        session.stage = "wave-acceptance"
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        await self._store.save(session)

    async def _open_wave_acceptance(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        # Kept for resume/tests; prove path is Verify (ADR 0006).
        await self._handoff_to_verify(tenant, room, session)

    async def _open_closeout_enter(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""
        brief = closeout_enter_brief(self._briefs, initiative=init, wave_id=wave, repo=repo)
        coach = closeout_enter_coach(initiative=init, wave_id=wave, repo=repo)
        god_token = await self._gates.open(session, brief=brief, coach=coach)
        if god_token:
            await self.after_judgment(tenant, room, session, god_token)

    async def _open_wave_signoff(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""
        pr_url = session.slots.get("wave_pr_url") or ""
        brief = wave_signoff_brief(
            self._briefs,
            initiative=init,
            wave_id=wave,
            repo=repo,
            pr_url=pr_url,
        )
        coach = wave_signoff_coach(initiative=init, wave_id=wave, repo=repo, pr_url=pr_url)
        god_token = await self._gates.open(session, brief=brief, coach=coach)
        if god_token:
            await self.after_judgment(tenant, room, session, god_token)

    async def _on_wave_complete(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        done_wave = session.slots.get("active_wave") or ""
        wave_ids = [w for w in (session.slots.get("wave_ids") or "").split(",") if w]
        remaining = [w for w in wave_ids if w != done_wave]
        # Mark done wave; pick next ready for this repo baton (serial within repo).
        prior = session.slots.get("done_waves") or ""
        done_set = {x for x in prior.split(",") if x}
        if done_wave:
            done_set.add(done_wave)
        session.slots["done_waves"] = ",".join(sorted(done_set))
        if remaining:
            nxt = remaining[0]
            session.slots["active_wave"] = nxt
            session.stage = _WAVE_ENTRY
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._poster.post_status(
                room,
                f"Coder finished `{done_wave}` — next wave `{nxt}` on `{repo}`.",
                EventType.PROGRESS,
                identity_handle=self._voice(session),
            )
            await self._continue_wave(tenant, room, session)
            return
        await self._leases.release(tenant=tenant.slug, repo=repo, holder=self.role_id)
        session.stage = "wave-complete"
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        await self._store.save(session)
        await self._poster.post_status(
            room,
            f"Coder complete for **{init}** repo=`{repo}` — lease released.",
            EventType.DONE,
            {"status": "coder_repo_complete", "initiative": init, "repo": repo},
            identity_handle=self._voice(session),
        )
