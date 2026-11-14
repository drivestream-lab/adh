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
from src.adh_agents.programmes.coder.dirty import assert_clean_worktree, sync_clean_integration
from src.adh_agents.programmes.coder.forge_ops import (
    land_wave_pr,
    move_wave_board_status,
    open_wave_draft_pr,
    pick_wave_issue_url,
)
from src.adh_agents.programmes.coder.gates import (
    closeout_enter_brief,
    closeout_enter_coach,
    wave_acceptance_brief,
    wave_acceptance_coach,
    wave_signoff_brief,
    wave_signoff_coach,
)
from src.adh_agents.programmes.coder.paths import wave_branch, wave_execution_report_path
from src.adh_agents.programmes.coder.repo_lease import CoderRepoLeaseStore
from src.adh_agents.programmes.coder.review import run_wave_review
from src.adh_agents.programmes.coder.roles import is_coder_role
from src.adh_agents.programmes.dev.impact_repos import resolve_repo_root
from src.adh_agents.programmes.pm.validation_report import impact_map_path
from src.adh_agents.runtime.agentic_decide import decide_catalogue_outcome
from src.adh_agents.runtime.gate_opener import GateOpener
from src.adh_agents.runtime.work_models import (
    AWAITING_NONE,
    PROGRAMME_CODER,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import CoderAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.pm_workspace_service import PmWorkspaceService, prd_path
from src.infra_services.prompt_service import PromptService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.infra_services.workflow_catalogue_service import WorkflowCatalogueService
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext

_BATON_TYPE = "coder.wave"
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
    ) -> None:
        super().__init__()
        self._store = store
        self._batons = batons
        self._poster = poster
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
        self._settings = CoderAgentSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
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
        await self._continue_wave(tenant, room, session)

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        del tenant
        return []

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        stage = (session.stage or "").strip()
        allowed = list(session.open_brief.reply_tokens) if session.open_brief else []
        matched = normalize_reply(token, allowed) or (token or "").strip().lower()
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""

        if matched in {HOLD, "park"} or "hold" in matched:
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._poster.post_status(
                room,
                f"Coder parked **{init}** `{wave}` on `{repo}`.",
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
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
            identity_handle=self.role_id,
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
        raw_waves = payload.get("wave_ids")
        wave_ids: list[str] = [str(x) for x in raw_waves] if isinstance(raw_waves, list) else []
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
                identity_handle=self.role_id,
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

        session = AgentWorkSession(
            role_id=self.role_id,
            tenant_slug=tenant.slug,
            room=collab,
            work_id=f"{init}:{repo}",
            programme=PROGRAMME_CODER,
            stage=_WAVE_ENTRY,
            awaiting=AWAITING_NONE,
            slots={
                "initiative": init,
                "repo": repo,
                "wave_ids": ",".join(wave_ids),
                "active_wave": wave_ids[0] if wave_ids else "",
                "coder_handle": baton.to_role,
                "board_seed_marker": str(payload.get("board_seed_marker") or ""),
                "board_issue_urls": " ".join(board_urls),
                "coder_spine": "c2_leased",
                "lease_key": lease.key,
                "baton_idempotency_key": baton.idempotency_key or "",
            },
        )
        await self._store.save(session)
        await self._poster.post_status(
            collab,
            (
                f"Coder leased `{repo}` for **{init}** "
                f"(waves={','.join(wave_ids) or 'n/a'}; entry=`{_WAVE_ENTRY}`)."
            ),
            EventType.PROGRESS,
            {"status": "coder_leased", "initiative": init, "repo": repo},
            identity_handle=self.role_id,
        )
        await self._continue_wave(tenant, collab, session)
        done = await self._batons.mark_done(baton, ttl=ttl)
        return Rollup(
            baton_id=done.id,
            role=self.role_id,
            status=BatonStatus.DONE,
            summary=f"coder_walk:{repo}:{session.stage}",
            correlation_id=baton.correlation_id,
            artefact_refs=list(baton.artefact_refs or []),
        )

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
            if stage not in _WAVE_CHAIN:
                await self._poster.post_status(
                    room,
                    f"Coder stalled — unknown YAML stage `{stage}`.",
                    EventType.STALL,
                    identity_handle=self.role_id,
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
                identity_handle=self.role_id,
            )
            return False

        if stage in _SKILL_NODES or node.is_skill():
            evidence, ok = await self._run_skill_stage(tenant, room, session, stage)
            if not ok:
                return False
            outcome = await self._decide_outcome(session, stage, evidence, node)
            if outcome in {"failed", "blocked"} or node.outcomes.get(outcome) == "workflow-stop":
                await self._poster.post_status(
                    room,
                    f"Coder stalled on `{stage}` outcome `{outcome}`.",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return False
            self._navigator.advance(session, outcome)
            await self._store.save(session)
            return True

        if stage == "wave-in-progress-action":
            if not await self._run_board_status(tenant, room, session, status="in_progress"):
                return False
            self._navigator.advance(session, "pass")
            await self._store.save(session)
            return True

        if stage == "wave-pr-action":
            if not await self._run_wave_pr(tenant, room, session):
                return False
            self._navigator.advance(session, "pass")
            await self._store.save(session)
            return True

        if stage == "wave-done-action":
            if not await self._run_board_status(tenant, room, session, status="done"):
                return False
            self._navigator.advance(session, "pass")
            await self._store.save(session)
            return True

        if stage == "wave-acceptance":
            await self._open_wave_acceptance(tenant, room, session)
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
            identity_handle=self.role_id,
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
                identity_handle=self.role_id,
            )
            return "", False
        try:
            assert_clean_worktree(root, label=repo)
            sync_clean_integration(root, branch=(tenant.integration_branch or "develop"))
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Coder refuse `{stage}` on `{repo}`: {exc}",
                EventType.STALL,
                {"status": "coder_dirty_or_sync", "repo": repo, "stage": stage},
                identity_handle=self.role_id,
            )
            return "", False

        prd_abs = str((Path(tenant.meta_root).expanduser() / prd_path(init)).resolve())
        impact_abs = str((Path(tenant.meta_root).expanduser() / impact_map_path(init)).resolve())
        await self._poster.post_status(
            room,
            f"Coder running YAML skill `{stage}` for **{init}** `{wave}` on `{repo}`…",
            EventType.PROGRESS,
            {"status": "coder_skill_start", "node": stage, "repo": repo},
            identity_handle=self.role_id,
        )
        branch = wave_branch(initiative=init, wave_id=wave, repo=repo)
        session.slots["head_ref"] = branch
        session.slots["base_ref"] = (tenant.integration_branch or "develop").strip() or "develop"
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
                    identity_handle=self.role_id,
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
                identity_handle=self.role_id,
            )
            return "", False
        if not result.ok:
            await self._poster.post_status(
                room,
                f"`{stage}` exit {result.exit_code} on `{repo}`.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return (result.output or "")[:8000], False
        session.slots[f"skill:{stage}:{repo}"] = "ok"
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
                identity_handle=self.role_id,
            )
            return False
        await self._poster.post_status(
            room,
            (f"Coder board `{wave}` → **{status}** " f"({result.detail or result.url or 'ok'})."),
            EventType.PROGRESS,
            {"status": f"coder_board_{status}", "wave": wave, "repo": repo},
            identity_handle=self.role_id,
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
                identity_handle=self.role_id,
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
                identity_handle=self.role_id,
            )
            return False
        try:
            assert_clean_worktree(root, label=repo)
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Coder refuse wave-pr-action: {exc}",
                EventType.STALL,
                identity_handle=self.role_id,
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
                identity_handle=self.role_id,
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
            identity_handle=self.role_id,
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
                identity_handle=self.role_id,
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
                sync_clean_integration(root, branch=(tenant.integration_branch or "develop"))
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Coder wave merge failed: {exc}",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return False
        session.slots["wave_merged"] = "true"
        session.slots["wave_merge_sha"] = result.url or ""
        await self._poster.post_status(
            room,
            f"Coder merged wave `{wave}` for **{init}** on `{repo}` ({result.url or 'ok'}).",
            EventType.DONE,
            {"status": "coder_wave_merged", "wave": wave, "repo": repo},
            identity_handle=self.role_id,
        )
        return True

    async def _open_wave_acceptance(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("active_wave") or ""
        pr_url = session.slots.get("wave_pr_url") or ""
        review = await run_wave_review(
            self._prompts,
            initiative=init,
            wave_id=wave,
            repo=repo,
            purpose="wave-acceptance",
            reply_tokens=[WAVE_ACCEPTED, ANOTHER_ROUND, HOLD],
            tip_excerpt=pr_url or "(no PR url yet)",
        )
        brief = wave_acceptance_brief(
            self._briefs,
            initiative=init,
            wave_id=wave,
            repo=repo,
            pr_url=pr_url,
            recommend=review.recommend,
            bluf=review.bluf,
            example=review.example,
            locking=review.locking,
            not_locking=review.not_locking,
            revise_if=review.revise_if,
        )
        coach = wave_acceptance_coach(
            initiative=init,
            wave_id=wave,
            repo=repo,
            pr_url=pr_url,
            recommend=review.recommend,
            bluf=review.bluf,
            example=review.example,
        )
        god_token = await self._gates.open(session, brief=brief, coach=coach)
        if god_token:
            await self.after_judgment(tenant, room, session, god_token)

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
                identity_handle=self.role_id,
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
            identity_handle=self.role_id,
        )
