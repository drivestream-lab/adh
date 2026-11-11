"""Dev YAML development programme — workflow.yaml ``development`` entry walker."""

from __future__ import annotations

import json
from pathlib import Path

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.catalogue.navigator import HermesNavigatorService
from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.gate_coach import TokenAction
from src.adh_agents.collaboration.human_replies import (
    ACCEPT_TDD_ADR,
    ANOTHER_ROUND,
    AUTHORIZE_BOARD,
    CODING_READY,
    HOLD,
    MERGE_SPEC_PR,
    REVISE_ENGG,
    normalize_reply,
)
from src.adh_agents.execution.dispatch_service import HermesDispatchService
from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.dev.board_seed import (
    board_seed_preconditions,
    mark_board_seeded,
)
from src.adh_agents.programmes.dev.debate import DebateResult, run_dev_debate
from src.adh_agents.programmes.dev.entry import resolve_dev_entry
from src.adh_agents.programmes.dev.forge_ops import land_spec_pr, open_spec_draft_pr
from src.adh_agents.programmes.dev.gates import (
    board_authorize_brief,
    board_authorize_coach,
    coding_ready_brief,
    coding_ready_coach,
    spec_merge_brief,
    spec_merge_coach,
    tdd_adr_brief,
    tdd_adr_coach,
)
from src.adh_agents.programmes.dev.impact_repos import (
    parse_affected_repos,
    resolve_repo_root,
)
from src.adh_agents.programmes.dev.paths import (
    implementation_plan_path,
    spec_slice_path,
    technical_review_path,
    workmanifest_path,
)
from src.adh_agents.programmes.dev.revise import apply_revise_engg_slots, is_post_board
from src.adh_agents.programmes.pm.validation_report import impact_map_path
from src.adh_agents.runtime.agentic_decide import decide_catalogue_outcome
from src.adh_agents.runtime.gate_opener import CoachSpec, GateOpener
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
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.litellm_service import LiteLLMService
from src.infra_services.pm_workspace_service import PmWorkspaceService, prd_path
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.infra_services.workflow_catalogue_service import WorkflowCatalogueService
from src.models.buzz_models import EventType, TaskEventCreate, TaskEventKind, TaskState
from src.models.tenant_models import TenantContext

_ENTRY = "spec-draft"
_STAGE_DONE = "board-seeded"
# E1 fence — stop after board seed (coder / wave-* is later).
_E1_TERMINAL = "board-tickets-action"

_PASS_CHAIN = (
    "spec-draft",
    "spec-pr-action",
    "initiative-feasibility",
    "spec-technical-review",
    "technical-review-approval",
    "spec-implementation-plan",
    "coding-readiness",
    "spec-merge",
    "board-tickets-action",
)


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
        navigator: HermesNavigatorService,
        catalogue: WorkflowCatalogueService,
        forge: ForgeActionService,
        github: GitHubAppService,
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
        self._navigator = navigator
        self._catalogue = catalogue
        self._forge = forge
        self._github = github
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
                f"Holding Dev YAML development for {session.initiative}.",
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
            return

        if stage == "technical-review-approval":
            await self._on_tdd_token(tenant, room, session, matched)
            return
        if stage == "coding-readiness":
            await self._on_coding_token(tenant, room, session, matched)
            return
        if stage == "spec-merge":
            await self._on_spec_merge_token(tenant, room, session, matched)
            return
        if stage == "board-tickets-action":
            await self._on_board_token(tenant, room, session, matched)
            return
        if stage == "spec-human-decision":
            # Clarification checkpoint: any non-hold token continues (YAML pass).
            if matched == HOLD:
                return
            self._navigator.advance(session, "pass")
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._run_spine(tenant, room, session)
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
            stage=_ENTRY,
            slots={
                "prd_pr_url": pr_url,
                "pr_url": pr_url,
                "baton_key": baton.idempotency_key,
            },
        )
        await self._store.save(session)
        await self._poster.post_status(
            collab,
            (
                f"Dev claimed `dev.engg_think` for **{init}** — "
                f"walking YAML `development` from `{_ENTRY}`."
            ),
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
                summary="dev yaml development bound",
                correlation_id=baton.correlation_id,
            )
        except Exception as exc:
            await self._batons.mark_done(baton, ttl=ttl, error=str(exc))
            await self._poster.post_status(
                collab,
                f"Dev YAML development failed for **{init}**: {exc}",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="dev yaml development failed",
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
                stage=_ENTRY,
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
                    "continue current YAML gates (or `hold`)."
                ),
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
            return
        session.slots = apply_revise_engg_slots(session.slots)
        session.stage = session.slots.get("reopen_stage") or _ENTRY
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        await self._store.save(session)
        await self._poster.post_status(
            room,
            (
                f"**Revise engg** for **{session.initiative}** — prior board seed "
                f"marked superseded; reopening `{session.stage}`."
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

    # ── YAML spine ─────────────────────────────────────────────────────

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
        if not (session.stage or "").strip():
            session.stage = _ENTRY
        if (session.slots.get("board_seeded") or "").lower() in {"1", "true", "yes"}:
            session.stage = _STAGE_DONE
        await self._store.save(session)
        await self._set_task_running(session)

        # Safety: never invent hops outside the catalogue development chain.
        if session.stage == _STAGE_DONE:
            await self._poster.post_status(
                room,
                (
                    f"**{init}** board already seeded (YAML E1 fence). "
                    f"Reply `{REVISE_ENGG}` to reopen from `{_ENTRY}`."
                ),
                EventType.DONE,
                identity_handle=self.role_id,
            )
            return

        # Walk until a gate or terminal.
        for _ in range(24):
            if session.awaiting in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION):
                return
            stage = (session.stage or "").strip()
            if stage == _STAGE_DONE:
                return
            if stage not in _PASS_CHAIN and stage not in {
                "spec-human-decision",
                "workflow-stop",
            }:
                await self._poster.post_status(
                    room,
                    f"Dev stalled — unknown YAML stage `{stage}` (not in development pass chain).",
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
        """Run current catalogue node. True = keep walking; False = waiting/stalled/done."""
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

        if node.is_skill():
            evidence, ok = await self._run_skill_stage(tenant, room, session, stage)
            if not ok:
                return False
            outcome = await decide_catalogue_outcome(
                self._litellm,
                role_id=self.role_id,
                node_id=stage,
                initiative=session.initiative or "",
                allowed_outcomes=list(node.outcomes.keys()),
                evidence=evidence,
            )
            await self._poster.post_status(
                room,
                f"Dev decided YAML outcome `{outcome}` for `{stage}`.",
                EventType.PROGRESS,
                {"status": "dev_outcome", "node": stage, "outcome": outcome},
                identity_handle=self.role_id,
            )
            nxt = node.outcomes.get(outcome)
            if outcome == "failed" or nxt == "workflow-stop":
                await self._poster.post_status(
                    room,
                    f"Dev stalled on `{stage}` outcome `{outcome}`.",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return False
            self._navigator.advance(session, outcome)
            await self._store.save(session)
            return True

        if node.is_external_action():
            if stage == "spec-pr-action":
                evidence, ok = await self._run_spec_pr_action(tenant, room, session)
                if not ok:
                    return False
                outcome = await decide_catalogue_outcome(
                    self._litellm,
                    role_id=self.role_id,
                    node_id=stage,
                    initiative=session.initiative or "",
                    allowed_outcomes=list(node.outcomes.keys()),
                    evidence=evidence,
                )
                await self._poster.post_status(
                    room,
                    f"Dev decided YAML outcome `{outcome}` for `{stage}`.",
                    EventType.PROGRESS,
                    {"status": "dev_outcome", "node": stage, "outcome": outcome},
                    identity_handle=self.role_id,
                )
                if outcome != "pass":
                    await self._poster.post_status(
                        room,
                        f"Dev stalled on `{stage}` outcome `{outcome}`.",
                        EventType.STALL,
                        identity_handle=self.role_id,
                    )
                    return False
                self._navigator.advance(session, outcome)
                await self._store.save(session)
                return True
            if stage == "spec-merge":
                await self._open_spec_merge_gate(tenant, room, session)
                return False
            if stage == "board-tickets-action":
                await self._open_board_gate(tenant, room, session)
                return False
            await self._poster.post_status(
                room,
                f"Dev E1 does not auto-run external-action `{stage}` yet (coder lane).",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return False

        if node.is_human_checkpoint():
            if stage == "technical-review-approval":
                await self._open_tdd_gate(tenant, room, session)
                return False
            if stage == "coding-readiness":
                await self._open_coding_gate(tenant, room, session)
                return False
            # Generic clarification checkpoint
            await self._open_clarification_gate(tenant, room, session, stage)
            return False

        await self._poster.post_status(
            room,
            f"Unhandled catalogue node type for `{stage}` ({node.type}).",
            EventType.STALL,
            identity_handle=self.role_id,
        )
        return False

    async def _run_skill_stage(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, stage: str
    ) -> tuple[str, bool]:
        """Run skill(s); return (evidence for outcome decide, ok)."""
        init = session.initiative or ""
        repos = self._impacted(tenant, init)
        if not repos:
            await self._poster.post_status(
                room,
                f"No impacted code repos in Impact-Map for **{init}** — cannot run `{stage}`.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return "", False

        ws_root = self._tenants.workspace_root()
        prd_abs = str((Path(tenant.meta_root).expanduser() / prd_path(init)).resolve())
        impact_abs = str((Path(tenant.meta_root).expanduser() / impact_map_path(init)).resolve())
        await self._poster.post_status(
            room,
            f"Dev running YAML skill `{stage}` for **{init}** across {len(repos)} repo(s)…",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

        # spec-draft: every affected repo. Other skills: primary (first) + note others.
        targets = repos if stage == "spec-draft" else repos[:1]
        evidence_chunks: list[str] = []
        for hit in targets:
            root = resolve_repo_root(ws_root, hit.repo)
            if root is None:
                await self._poster.post_status(
                    room,
                    (
                        f"Missing local checkout for `{hit.repo}` under "
                        f"`{ws_root}` — stall `{stage}`."
                    ),
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return "", False
            extra = (
                f"Repo under development: {hit.repo} ({hit.service}). "
                f"Absolute PRD path (read-only): {prd_abs}. "
                f"Absolute Impact-Map path: {impact_abs}. "
                f"All impacted repos: {', '.join(r.repo for r in repos)}. "
                "Write artefacts in THIS repo only (docs/specification/**). "
                "Do not implement product code. Do not forge PRs. "
                "When finished, state clearly whether the skill pass is clean or blocked."
            )
            try:
                result = await self._dispatch.run_skill_node(
                    tenant,
                    stage,
                    init,
                    on_progress=self._progress_cb(room),
                    workspace=root,
                    repo=hit.repo,
                    extra_prompt=extra,
                    prd_path=prd_abs,
                    reports_dir="docs/specification/reports",
                )
            except Exception as exc:
                await self._poster.post_status(
                    room,
                    f"`{stage}` failed on `{hit.repo}`: {exc}",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return "", False
            if not result.ok:
                await self._poster.post_status(
                    room,
                    f"`{stage}` exit {result.exit_code} on `{hit.repo}`.",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return (result.output or "")[:8000], False
            session.slots[f"skill:{stage}:{hit.repo}"] = "ok"
            evidence_chunks.append(f"## {hit.repo}\n{(result.output or '')[:4000]}")

        if stage == "spec-implementation-plan":
            primary = resolve_repo_root(ws_root, targets[0].repo)
            plan = implementation_plan_path(init)
            wm = workmanifest_path(init)
            session.slots["implementation_plan_path"] = plan
            session.slots["workmanifest_path"] = wm
            session.slots["plan_repo"] = targets[0].repo
            if primary is None or not (primary / plan).is_file():
                await self._poster.post_status(
                    room,
                    f"Implementation plan missing at `{plan}` in `{targets[0].repo}` after skill.",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return "\n\n".join(evidence_chunks), False
            session.slots["implementation_plan_current"] = "true"
            if (primary / wm).is_file():
                session.slots["workmanifest_contract_pass"] = "true"
            else:
                await self._poster.post_status(
                    room,
                    f"WorkManifest missing at `{wm}` — fail closed (no soft-pass).",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return "\n\n".join(evidence_chunks), False
        if stage == "spec-technical-review":
            session.slots["technical_review_path"] = technical_review_path(init)
            session.slots["tech_repo"] = targets[0].repo
        await self._store.save(session)
        return "\n\n".join(evidence_chunks), True

    async def _run_spec_pr_action(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> tuple[str, bool]:
        if not forge_allowed(self.role_id, "open_draft_pr"):
            await self._poster.post_status(
                room,
                "Forge ACL denies open_draft_pr for adh.dev.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return "", False
        init = session.initiative or ""
        repos = self._impacted(tenant, init)
        pr_urls: list[str] = []
        pr_meta: list[dict[str, str]] = []
        ws_root = self._tenants.workspace_root()
        await self._poster.post_status(
            room,
            f"Dev YAML `spec-pr-action` — opening draft spec PRs for **{init}**…",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )
        for hit in repos:
            root = resolve_repo_root(ws_root, hit.repo)
            if root is None:
                await self._poster.post_status(
                    room,
                    f"Missing checkout `{hit.repo}` under `{ws_root}` for spec-pr-action.",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return "", False
            branch = f"docs/spec-{init.lower()}"
            slice_rel = spec_slice_path(init, hit.repo, map_spec=hit.spec_to_create)
            # Collect any new/changed spec docs under docs/specification/
            push_paths = []
            spec_root = root / "docs" / "specification"
            if spec_root.is_dir():
                for path in spec_root.rglob("*"):
                    if path.is_file() and path.suffix in {".md", ".yaml", ".yml"}:
                        push_paths.append(str(path.relative_to(root)))
            if slice_rel not in push_paths and (root / slice_rel).is_file():
                push_paths.append(slice_rel)
            if not push_paths:
                # Still open a thin PR body so the chain can continue with evidence.
                push_paths = []
            body_rel = f"docs/specification/reports/Spec-PR-Body-{init}-{hit.repo}.md"
            try:
                result = await open_spec_draft_pr(
                    forge=self._forge,
                    github=self._github,
                    workspace=self._workspace,
                    tenant=tenant,
                    repo=hit.repo,
                    repo_root=root,
                    initiative=init,
                    branch=branch,
                    body_rel=body_rel,
                    title=f"docs({init}): spec draft — {hit.repo}",
                    push_paths=push_paths or [body_rel],
                )
            except Exception as exc:
                await self._poster.post_status(
                    room,
                    f"spec-pr-action failed for `{hit.repo}`: {exc}",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return "", False
            url = result.url or ""
            pr_urls.append(url)
            pr_meta.append(
                {
                    "repo": hit.repo,
                    "url": url,
                    "number": str(result.pr_number or ""),
                    "branch": branch,
                }
            )
            await self._poster.post_status(
                room,
                f"Opened draft spec PR for `{hit.repo}`: {url or '(no url)'}",
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
        evidence = "\n".join(
            f"- {r}: {u}" for r, u in zip([m["repo"] for m in pr_meta], pr_urls, strict=False)
        )
        session.slots["spec_pr_urls"] = " | ".join(u for u in pr_urls if u)
        session.slots["spec_pr_meta"] = json.dumps(pr_meta)
        await self._store.save(session)
        return evidence, True

    # ── gates ──────────────────────────────────────────────────────────

    async def _open_tdd_gate(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.initiative or ""
        artefact = session.slots.get("technical_review_path") or technical_review_path(init)
        repo = session.slots.get("tech_repo") or ""
        root = resolve_repo_root(self._tenants.workspace_root(), repo) if repo else None
        ctx = ""
        if root is not None and (root / artefact).is_file():
            ctx = (root / artefact).read_text(encoding="utf-8")[:8000]
        debate = await self._debate_hop(
            purpose="tdd-adr-acceptance",
            initiative=init,
            context=ctx or artefact,
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

    async def _open_coding_gate(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.initiative or ""
        plan = session.slots.get("implementation_plan_path") or implementation_plan_path(init)
        repo = session.slots.get("plan_repo") or ""
        root = resolve_repo_root(self._tenants.workspace_root(), repo) if repo else None
        plan_body = ""
        if root is not None and (root / plan).is_file():
            plan_body = (root / plan).read_text(encoding="utf-8")[:8000]
            session.slots["implementation_plan_current"] = "true"
        if not session.slots.get("workmanifest_contract_pass"):
            await self._poster.post_status(
                room,
                "coding-readiness blocked — WorkManifest predicate not set (fail closed).",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        debate = await self._debate_hop(
            purpose="coding-readiness",
            initiative=init,
            context=plan_body or plan,
            reply_tokens=[CODING_READY, ANOTHER_ROUND, HOLD],
            session=session,
        )
        brief = coding_ready_brief(self._briefs, initiative=init, plan_path=plan, debate=debate)
        god = await self._gates.open(
            session,
            brief=brief,
            awaiting=AWAITING_JUDGMENT,
            coach=coding_ready_coach(initiative=init, plan_path=plan, debate=debate),
        )
        if god:
            await self.after_judgment(tenant, room, session, god)

    async def _open_spec_merge_gate(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.initiative or ""
        urls = session.slots.get("spec_pr_urls") or ""
        debate = await self._debate_hop(
            purpose="spec-merge",
            initiative=init,
            context=urls or "spec PRs",
            reply_tokens=[MERGE_SPEC_PR, "go ahead", HOLD],
            session=session,
        )
        brief = spec_merge_brief(self._briefs, initiative=init, pr_urls=urls, debate=debate)
        god = await self._gates.open(
            session,
            brief=brief,
            awaiting=AWAITING_AUTHORIZATION,
            coach=spec_merge_coach(initiative=init, pr_urls=urls, debate=debate),
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

    async def _open_clarification_gate(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, stage: str
    ) -> None:
        init = session.initiative or ""
        debate = await self._debate_hop(
            purpose=stage,
            initiative=init,
            context=stage,
            reply_tokens=[ANOTHER_ROUND, HOLD],
            session=session,
        )
        recommend = (debate.recommend if debate else "") or ANOTHER_ROUND
        brief = self._briefs.build_brief(
            purpose=stage,
            node_id=stage,
            question=f"Spec clarification for **{init}** at `{stage}`?",
            recommend=recommend,
            recommend_why=debate.bluf if debate else "Continue development chain",
            bluf=debate.bluf if debate else "",
            example=f"reply `{ANOTHER_ROUND}`",
            reply_tokens=[ANOTHER_ROUND, HOLD],
        )
        coach = CoachSpec(
            i_did=f"Reached YAML checkpoint `{stage}` for **{init}**.",
            recommend=recommend,
            recommend_why="Continue or hold.",
            outside_adh="Skim the open artefacts in Cursor if clarification is unclear.",
            example=f"reply `{ANOTHER_ROUND}`",
            tokens=[
                TokenAction(ANOTHER_ROUND, "continue development chain"),
                TokenAction(HOLD, "park"),
            ],
            hop=stage,
        )
        god = await self._gates.open(session, brief=brief, awaiting=AWAITING_JUDGMENT, coach=coach)
        if god:
            await self.after_judgment(tenant, room, session, god)

    # ── gate tokens ────────────────────────────────────────────────────

    async def _on_tdd_token(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        allowed = [ACCEPT_TDD_ADR, ANOTHER_ROUND, HOLD]
        matched = normalize_reply(token, allowed) or token
        if matched == ANOTHER_ROUND:
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            self._navigator.advance(session, "findings")
            await self._store.save(session)
            await self._run_spine(tenant, room, session)
            return
        if matched == ACCEPT_TDD_ADR:
            session.slots["tdd_adr_accepted"] = "true"
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            self._navigator.advance(session, "pass")
            await self._store.save(session)
            await self._run_spine(tenant, room, session)
            return
        await self._poster.post_status(
            room,
            f"Unrecognized technical-review-approval reply `{token}`.",
            EventType.STALL,
            identity_handle=self.role_id,
        )

    async def _on_coding_token(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        allowed = [CODING_READY, ANOTHER_ROUND, HOLD]
        matched = normalize_reply(token, allowed) or token
        if matched == ANOTHER_ROUND:
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            self._navigator.advance(session, "findings")
            await self._store.save(session)
            await self._run_spine(tenant, room, session)
            return
        if matched == CODING_READY:
            if not session.slots.get("workmanifest_contract_pass"):
                await self._poster.post_status(
                    room,
                    "Cannot accept coding-ready — WorkManifest predicate missing.",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                return
            session.slots["coding_ready_accepted"] = "true"
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            self._navigator.advance(session, "pass")
            await self._store.save(session)
            await self._run_spine(tenant, room, session)
            return
        await self._poster.post_status(
            room,
            f"Unrecognized coding-readiness reply `{token}`.",
            EventType.STALL,
            identity_handle=self.role_id,
        )

    async def _on_spec_merge_token(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        allowed = [MERGE_SPEC_PR, "go ahead", HOLD]
        matched = normalize_reply(token, allowed) or token
        if matched == HOLD:
            return
        if matched not in {MERGE_SPEC_PR, "go ahead"}:
            await self._poster.post_status(
                room,
                f"Unrecognized spec-merge reply `{token}`.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        if not forge_allowed(self.role_id, "land_pull_request"):
            await self._poster.post_status(
                room,
                "Forge ACL denies land_pull_request for adh.dev.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        init = session.initiative or ""
        try:
            meta = json.loads(session.slots.get("spec_pr_meta") or "[]")
        except json.JSONDecodeError:
            meta = []
        if not meta:
            await self._poster.post_status(
                room,
                "No spec_pr_meta — cannot merge.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        await self._poster.post_status(
            room,
            f"Dev landing spec PR(s) for **{init}**…",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )
        for row in meta:
            repo = str(row.get("repo") or "")
            number = int(str(row.get("number") or "0") or 0)
            if not repo or number <= 0:
                continue
            try:
                await land_spec_pr(
                    forge=self._forge,
                    workspace=self._workspace,
                    repo=repo,
                    pr_number=number,
                    initiative=init,
                )
            except Exception as exc:
                await self._poster.post_status(
                    room,
                    f"spec-merge failed for `{repo}`#{number}: {exc}",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )
                session.awaiting = AWAITING_NONE
                session.open_brief = None
                await self._store.save(session)
                await self._open_spec_merge_gate(tenant, room, session)
                return
        session.slots["spec_pr_merged"] = "true"
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        self._navigator.advance(session, "pass")
        await self._store.save(session)
        await self._append_event(
            session,
            kind=TaskEventKind.LAND,
            purpose="spec-merge",
            payload={"initiative": init},
        )
        await self._run_spine(tenant, room, session)

    async def _on_board_token(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        matched = normalize_reply(token, [AUTHORIZE_BOARD, HOLD]) or token
        if matched != AUTHORIZE_BOARD:
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
        plan_repo = session.slots.get("plan_repo") or ""
        root = resolve_repo_root(self._tenants.workspace_root(), plan_repo) if plan_repo else None
        try:
            result = await self._dispatch.run_catalog_skill(
                tenant,
                "create-board-tickets",
                init,
                on_progress=self._progress_cb(room),
                workspace=root,
                repo=plan_repo,
                extra_prompt=(
                    f"Plan path: {session.slots.get('implementation_plan_path')}. "
                    f"WorkManifest: {session.slots.get('workmanifest_path')}."
                ),
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
            payload={"initiative": init, "yaml_terminal": _E1_TERMINAL},
        )
        await self._poster.post_status(
            room,
            (
                f"**{init}** board tickets seeded — Dev YAML E1 fence complete "
                f"(`{_E1_TERMINAL}`). Coder hire is later. "
                f"Reply `{REVISE_ENGG}` to reopen think."
            ),
            EventType.DONE,
            {"status": "board_seeded", "initiative": init},
            identity_handle=self.role_id,
        )

    # ── helpers ────────────────────────────────────────────────────────

    def _impacted(self, tenant: TenantContext, initiative: str):
        body = self._workspace.read_local(tenant, impact_map_path(initiative)) or ""
        return parse_affected_repos(body, meta_repo=tenant.meta_repo)

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
