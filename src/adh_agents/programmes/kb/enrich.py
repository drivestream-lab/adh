"""KB enrich programme — stub scaffold + LLM fill; Buzz light + Lead wait."""

from __future__ import annotations

from pathlib import Path

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.collaboration.brief_service import HermesBriefService
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
                f"Holding KB enrich PR for {session.initiative}.",
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
            return
        await self._open_enrich_pr(tenant, room, session)

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        await self._poster.post_status(
            room,
            f"Resume KB enrich `{work_id}`.",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
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
                f"Authorize opening a draft enrich PR for {init or 'KB'} "
                f"under `knowledge/` ({len(written)} head file(s))?"
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
        await self._poster.post_status(
            ops,
            (
                f"KB enrich prepared for **{init or baton.id}**.\n"
                f"Heads: {heads_preview or '(none)'}\n"
                f"**Next:** {self._briefs.format_brief_markdown(brief)}"
            ),
            EventType.PROGRESS,
            {
                "status": "kb_enrich_ready",
                "baton_id": baton.id,
                "heads": written,
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
            f"# KB enrich — {init}\n\n"
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
        except Exception as exc:
            await self._poster.post_status(
                room,
                (
                    f"KB enrich PR failed for {init}: {exc}. "
                    "Local heads kept. Reply `go ahead` to retry or `hold`."
                ),
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        session.stage = "kb-enrich-opened"
        session.slots["enrich_pr"] = pr_url
        await self._store.save(session)
        await self._poster.post_status(
            room,
            (
                f"KB enrich draft ready for **{init}**.\n"
                f"PR: {pr_url or 'n/a'}\n"
                f"**Next:** review/merge enrich PR on forge when satisfied."
            ),
            EventType.DONE,
            {"status": "kb_enrich_pr", "initiative": init, "pr": pr_url},
            identity_handle=self.role_id,
        )
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
