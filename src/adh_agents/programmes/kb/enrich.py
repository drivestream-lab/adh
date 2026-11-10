"""KB enrich programme — stub scaffold + LLM fill; coach + authorize land."""

from __future__ import annotations

from pathlib import Path

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.gate_coach import TokenAction
from src.adh_agents.collaboration.temp_papers import (
    PurgeContext,
    PurgeEvent,
    buzz_purge_notice,
    execute_purge,
)
from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.kb.heads import (
    HeadPatch,
    merge_llm_sections,
    stub_heads_from_signals,
    write_patches,
)
from src.adh_agents.runtime.work_models import (
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    PROGRAMME_KB,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import KbAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.litellm_service import LiteLLMService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext


class KbEnrichProgramme(BaseBusinessService):
    programme_id = PROGRAMME_KB
    role_id = "adh.kb"

    @inject
    def __init__(
        self,
        store: AgentWorkStore,
        batons: RedisBatonStore,
        poster: HermesBuzzPoster,
        tenants: TenantRegistryService,
        briefs: HermesBriefService,
        workspace: PmWorkspaceService,
        forge: ForgeActionService,
        litellm: LiteLLMService,
    ) -> None:
        super().__init__()
        self._store = store
        self._batons = batons
        self._poster = poster
        self._tenants = tenants
        self._briefs = briefs
        self._workspace = workspace
        self._forge = forge
        self._litellm = litellm
        self._settings = KbAgentSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        await self._poster.post_status(
            room,
            f"KB programme bound for {session.work_id}.",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        # Orchestrator already matched token against the open brief.
        lowered = (token or "").strip().lower()
        if "hold" in lowered:
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._poster.post_status(
                room,
                f"Holding knowledge docs for {session.initiative}.",
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
            return
        if session.stage == "kb-enrich-land":
            if "discard local" in lowered:
                await self._discard_local_after_land(tenant, room, session)
                return
            await self._land_enrich_pr(tenant, room, session)
            return
        await self._open_enrich_pr(tenant, room, session)

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        del tenant
        # Explicit resume only — no spam. Re-surface open brief if present via store caller.
        await self._poster.post_status(
            room,
            f"KB resume requested for `{work_id}` — open the outstanding knowledge gate if any.",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        del tenant
        return []

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
        ops = room or baton.ops_room
        init = (baton.initiative or "").strip().upper()
        payload = baton.payload or {}
        repo_ref = str(payload.get("repo_ref") or tenant.meta_repo)
        signals = _load_signals(tenant, init, repo_ref)
        stubs = stub_heads_from_signals(
            initiative=init,
            repo_ref=repo_ref,
            signals=signals,
            tenant_repos=dict(tenant.repos),
        )
        filled = await self._llm_fill(stubs, initiative=init, repo_ref=repo_ref)
        written = write_patches(Path(tenant.meta_root), filled, overwrite=False)
        session = AgentWorkSession(
            tenant_slug=tenant.slug,
            role_id=self.role_id,
            room=ops,
            work_id=f"KB-{init or baton.id}",
            initiative=init or None,
            programme=self.programme_id,
            stage="kb-enrich-authorize",
            slots={
                "repo_ref": repo_ref,
                "heads": ",".join(written),
                "baton_id": baton.id,
            },
        )
        brief = self._briefs.build_brief(
            purpose="kb-enrich",
            node_id="kb-enrich",
            question=(
                f"Authorize opening a draft knowledge docs PR for {init or 'KB'} "
                f"({len(written)} head file(s))?"
            ),
            example="Heads stay OKF-only (foundation/stacks/repos/contracts) — no initiatives/.",
            options=[
                "authorize kb_enrich_pr — open draft PR",
                "hold — keep local stubs only",
            ],
            recommend="authorize kb_enrich_pr",
            bluf="Nothing is pushed until you authorize.",
            reply_tokens=["go ahead", "authorize kb_enrich_pr", "hold"],
        )
        session.open_brief = brief
        session.awaiting = AWAITING_JUDGMENT
        await self._store.save(session)
        heads_preview = ", ".join(f"`{p}`" for p in written[:6])
        if len(written) > 6:
            heads_preview += f" (+{len(written) - 6} more)"
        await self._poster.post_human_next(
            ops,
            i_did=(
                f"Prepared knowledge head stubs for **{init or baton.id}** "
                f"({len(written)} file(s))."
            ),
            recommend="go ahead",
            recommend_why="Open a draft knowledge docs PR so heads can land on develop.",
            evidence=heads_preview or "(no heads written)",
            outside_adh=(
                "Skim the local `knowledge/` head files in Cursor before authorizing. "
                "Do **not** open the PR yourself on GitHub."
            ),
            tokens=[
                TokenAction(
                    "go ahead",
                    "open the draft knowledge docs PR, then ask you to land it",
                ),
                TokenAction("authorize kb_enrich_pr", "same as go ahead"),
                TokenAction("hold", "keep local stubs only — nothing pushed"),
            ],
            hop="kb-enrich",
            payload={
                "status": "kb_enrich_ready",
                "baton_id": baton.id,
                "heads": written,
                "purpose": "kb-enrich",
            },
            identity_handle=self.role_id,
        )
        done = await self._batons.mark_done(baton, ttl=ttl)
        return Rollup(
            baton_id=done.id,
            role=self.role_id,
            status=done.status,
            summary=f"KB enrich stubs ready ({len(written)} heads); awaiting Lead",
            correlation_id=done.correlation_id,
            artefact_refs=written,
            tools_used=["kb.stub", "kb.llm_fill"],
        )

    async def _llm_fill(
        self, stubs: list[HeadPatch], *, initiative: str, repo_ref: str
    ) -> list[HeadPatch]:
        out: list[HeadPatch] = []
        for stub in stubs:
            try:
                await self._litellm.initialize()
                text = await self._litellm.complete(
                    system=(
                        "You fill OKF knowledge head markdown. "
                        "Keep the same # title and ## section headings. "
                        "Replace (pending) with concise programme memory. "
                        "Never create initiatives/ paths or dump full PRDs. "
                        "Return markdown only."
                    ),
                    user=(
                        f"Initiative footnote: {initiative}\n"
                        f"Repo context: {repo_ref}\n\n"
                        f"Stub:\n{stub.contents}"
                    ),
                    max_tokens=1200,
                    temperature=0.2,
                )
                out.append(
                    HeadPatch(
                        relative_path=stub.relative_path,
                        contents=merge_llm_sections(stub.contents, text),
                    )
                )
            except Exception:
                self.logger.exception("KB LLM fill failed; keeping stub", path=stub.relative_path)
                out.append(stub)
        return out

    async def _open_enrich_pr(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        if not forge_allowed(self.role_id, "open_draft_pr"):
            await self._poster.post_status(
                room,
                "Forge ACL denies open_draft_pr for adh.kb.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        init = (session.initiative or "KB").strip().upper()
        heads = [h for h in (session.slots.get("heads") or "").split(",") if h]
        branch = f"kb/enrich-{init.lower().replace('_', '-')}"
        body_rel = f"prd/reports/{init}-kb-enrich-pr-body.md"
        body = (
            f"# Knowledge docs — {init}\n\n"
            "OKF heads only (`foundation` / `stacks` / `repos` / `contracts`). "
            "No `initiatives/` tree.\n\n"
            "## Files\n\n" + "\n".join(f"- `{h}`" for h in heads) + "\n"
        )
        self._workspace.write_local(tenant, body_rel, body)
        try:
            await self._workspace.push_paths_to_branch(
                tenant,
                branch=branch,
                relative_paths=[*heads, body_rel],
                commit_message=f"docs(knowledge): enrich heads after {init}",
            )
            app = self._workspace.pm_app_role()
            result = await self._forge.run_action(
                tenant,
                "open_draft_pr",
                app=app,
                title=f"docs(knowledge): enrich heads after {init}",
                body_path=body_rel,
                head_branch=branch,
                draft=True,
                labels=[],
                repo=tenant.meta_repo,
            )
            pr_url = result.url or ""
            pr_number = result.pr_number
        except Exception as exc:
            await self._poster.post_human_next(
                room,
                i_did=f"Tried to open the knowledge docs PR for **{init}** and hit an error.",
                recommend="go ahead",
                recommend_why=f"{exc}. Local heads kept.",
                outside_adh="Check local `knowledge/` files in Cursor, then retry here.",
                tokens=[
                    TokenAction("go ahead", "retry opening the draft knowledge docs PR"),
                    TokenAction("authorize kb_enrich_pr", "same as go ahead"),
                    TokenAction("hold", "keep local stubs only"),
                ],
                hop="kb-enrich",
                event_type=EventType.STALL,
                payload={"status": "kb_enrich_pr_failed", "initiative": init},
                identity_handle=self.role_id,
            )
            return
        session.slots["enrich_pr"] = pr_url
        if pr_number is not None:
            session.slots["enrich_pr_number"] = str(pr_number)
        # Immediately open land gate — never "merge on forge".
        await self._open_land_gate(
            tenant, room, session, init=init, pr_url=pr_url, pr_number=pr_number
        )

    async def _open_land_gate(
        self,
        tenant: TenantContext,
        room: str,
        session: AgentWorkSession,
        *,
        init: str,
        pr_url: str,
        pr_number: int | None,
    ) -> None:
        del tenant
        brief = self._briefs.build_brief(
            purpose="kb-enrich-land",
            node_id="kb-enrich-land",
            question=f"Authorize landing the knowledge docs PR for {init}?",
            example="I will undraft + merge, sync local develop, then purge temps.",
            options=[
                "authorize kb_enrich_land — merge now",
                "hold — leave draft open",
            ],
            recommend="authorize",
            bluf="Nothing merges until you authorize.",
            reply_tokens=["go ahead", "authorize kb_enrich_land", "hold"],
        )
        session.open_brief = brief
        session.awaiting = AWAITING_JUDGMENT
        session.stage = "kb-enrich-land"
        await self._store.save(session)
        await self._poster.post_human_next(
            room,
            i_did=f"Opened draft knowledge docs PR for **{init}**.",
            recommend="go ahead",
            recommend_why="Land heads onto develop when the draft looks right.",
            evidence=f"PR: {pr_url or 'n/a'}"
            + (f" (#{pr_number})" if pr_number is not None else ""),
            outside_adh=(
                "Review the knowledge docs PR in GitHub / Cursor. "
                "Do **not** merge on GitHub yourself — authorize here and I will land it."
            ),
            tokens=[
                TokenAction(
                    "go ahead",
                    "undraft + merge the knowledge docs PR, sync local develop, purge temps",
                ),
                TokenAction("authorize kb_enrich_land", "same as go ahead"),
                TokenAction("hold", "leave the draft open — nothing lands"),
            ],
            hop="kb-enrich-land",
            payload={
                "status": "kb_enrich_need_land",
                "initiative": init,
                "pr": pr_url,
                "pr_number": pr_number,
                "purpose": "kb-enrich-land",
            },
            identity_handle=self.role_id,
        )

    async def _land_enrich_pr(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        if not (
            forge_allowed(self.role_id, "prd_merge")
            or forge_allowed(self.role_id, "land_pull_request")
        ):
            await self._poster.post_status(
                room,
                "Forge ACL denies knowledge docs land for adh.kb.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        init = (session.initiative or "KB").strip().upper()
        pr_url = session.slots.get("enrich_pr") or ""
        pr_number = _int_slot(session.slots.get("enrich_pr_number")) or _pr_number_from_url(pr_url)
        if pr_number is None:
            await self._poster.post_status(
                room,
                f"Cannot land knowledge docs for {init} — missing PR number.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        try:
            app = self._workspace.pm_app_role()
            result = await self._forge.land_pull_request(
                app=app,
                repo=tenant.meta_repo,
                pr_number=pr_number,
                commit_title=f"docs(knowledge): land enrich after {init}",
                action="land_pull_request",
            )
        except Exception as exc:
            await self._poster.post_human_next(
                room,
                i_did=f"Tried to land knowledge docs PR #{pr_number} for **{init}** and failed.",
                recommend="go ahead",
                recommend_why=str(exc),
                outside_adh="Check the knowledge docs PR on GitHub, then retry here.",
                tokens=[
                    TokenAction("go ahead", "retry undraft + merge + sync"),
                    TokenAction("authorize kb_enrich_land", "same as go ahead"),
                    TokenAction("hold", "leave the draft open"),
                ],
                hop="kb-enrich-land",
                event_type=EventType.STALL,
                payload={"status": "kb_enrich_land_failed", "initiative": init},
                identity_handle=self.role_id,
            )
            return

        try:
            sync = self._workspace.sync_integration_branch(tenant)
        except ValidationError as exc:
            session.slots["land_sha"] = result.url or ""
            session.slots["sync_stall"] = "dirty"
            brief = self._briefs.build_brief(
                purpose="kb-enrich-land",
                node_id="kb-enrich-land",
                question=(
                    f"Knowledge docs PR #{pr_number} merged for {init}, but local meta is dirty. "
                    "Discard local changes so I can sync develop?"
                ),
                example="I will not silently overwrite dirty local meta.",
                options=[
                    "discard local — reset local meta to origin develop",
                    "hold — leave local as-is",
                ],
                recommend="discard local",
                bluf="Remote is landed; local must match.",
                reply_tokens=["discard local", "hold"],
            )
            session.open_brief = brief
            session.awaiting = AWAITING_JUDGMENT
            session.stage = "kb-enrich-land"
            await self._store.save(session)
            await self._poster.post_human_next(
                room,
                i_did=(
                    f"Merged knowledge docs PR #{pr_number} for **{init}**, "
                    "but local meta is dirty."
                ),
                recommend="discard local",
                recommend_why=str(exc),
                outside_adh="Inspect local dirty files in Cursor before discarding.",
                tokens=[
                    TokenAction(
                        "discard local",
                        "hard-reset local meta to origin develop, then purge temps",
                    ),
                    TokenAction("hold", "leave local dirty — purge deferred"),
                ],
                hop="kb-enrich-land",
                event_type=EventType.STALL,
                payload={"status": "kb_sync_stall", "initiative": init, "pr": pr_number},
                identity_handle=self.role_id,
            )
            return

        await self._finish_land(tenant, room, session, init=init, pr_number=pr_number, sync=sync)

    async def _discard_local_after_land(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = (session.initiative or "KB").strip().upper()
        pr_number = _int_slot(session.slots.get("enrich_pr_number")) or _pr_number_from_url(
            session.slots.get("enrich_pr") or ""
        )
        try:
            sync = self._workspace.sync_integration_branch(tenant, force=True)
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Could not discard/sync local meta for {init}: {exc}",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        await self._finish_land(
            tenant, room, session, init=init, pr_number=pr_number or 0, sync=sync
        )

    async def _finish_land(
        self,
        tenant: TenantContext,
        room: str,
        session: AgentWorkSession,
        *,
        init: str,
        pr_number: int,
        sync: dict[str, str],
    ) -> None:
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        session.stage = "kb-enrich-landed"
        session.slots["sync_sha"] = sync.get("sha") or ""
        session.slots.pop("sync_stall", None)
        await self._store.save(session)
        await self._poster.post_status(
            room,
            (
                f"Landed knowledge docs PR #{pr_number} for **{init}** "
                f"(local develop synced to `{sync.get('sha') or 'origin'}`)."
            ),
            EventType.DONE,
            {"status": "kb_enrich_landed", "initiative": init, "pr": pr_number},
            identity_handle=self.role_id,
        )
        # Purge only after successful land (U4).
        purged = execute_purge(
            self._workspace,
            tenant,
            PurgeEvent.KB_ENRICH_DONE,
            PurgeContext(initiative=init, meta_repo=tenant.meta_repo),
        )
        if purged:
            await self._poster.post_status(
                room,
                buzz_purge_notice(PurgeEvent.KB_ENRICH_DONE, init, purged),
                EventType.PROGRESS,
                {
                    "status": "temps_purged",
                    "event": PurgeEvent.KB_ENRICH_DONE.value,
                    "initiative": init,
                    "paths": purged,
                },
                identity_handle=self.role_id,
            )


def _load_signals(tenant: TenantContext, init: str, repo_ref: str) -> list[str]:
    safe = repo_ref.replace("/", "-")
    rel = f"prd/reports/{init}-read-walk-{safe}.md"
    path = Path(tenant.meta_root).expanduser() / rel
    if not path.is_file():
        return []
    signals: list[str] = []
    in_signals = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "## Signals":
            in_signals = True
            continue
        if in_signals:
            if line.startswith("## "):
                break
            if line.startswith("- `") and line.endswith("`"):
                signals.append(line[3:-1])
    return signals


def _pr_number_from_url(pr_url: str) -> int | None:
    parts = (pr_url or "").rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "pull" and parts[-1].isdigit():
        return int(parts[-1])
    return None


def _int_slot(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if text.isdigit():
        return int(text)
    return None
