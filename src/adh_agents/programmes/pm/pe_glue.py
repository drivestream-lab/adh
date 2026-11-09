"""PM glue for Gate‑1 — answer PE questions; authorize prd_merge after attest."""

from __future__ import annotations

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
from src.adh_agents.runtime.work_models import (
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    PROGRAMME_META_PM,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import PmAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext


class PmPeGlueProgramme(BaseBusinessService):
    """Handles pm.pe_questions + pm.prd_merge_ready batons (D2)."""

    programme_id = "pm-pe-glue"
    role_id = "adh.pm"

    @inject
    def __init__(
        self,
        store: AgentWorkStore,
        batons: RedisBatonStore,
        poster: HermesBuzzPoster,
        briefs: HermesBriefService,
        forge: ForgeActionService,
        workspace: PmWorkspaceService,
        tenants: TenantRegistryService,
    ) -> None:
        super().__init__()
        self._store = store
        self._batons = batons
        self._poster = poster
        self._briefs = briefs
        self._forge = forge
        self._workspace = workspace
        self._tenants = tenants
        self._settings = PmAgentSettings.get_instance()

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
        if baton.type == "pm.pe_questions":
            await self._on_pe_questions(tenant, room or baton.ops_room, baton)
        elif baton.type == "pm.prd_merge_ready":
            await self._on_merge_ready(tenant, room or baton.ops_room, baton)
        else:
            await self._batons.mark_done(baton, ttl=ttl, error="unsupported")
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary=f"unsupported baton {baton.type}",
                correlation_id=baton.correlation_id,
                error="unsupported",
            )
        done = await self._batons.mark_done(baton, ttl=ttl)
        return Rollup(
            baton_id=done.id,
            role=self.role_id,
            status=done.status,
            summary=f"PM handled {baton.type}",
            correlation_id=done.correlation_id,
        )

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        # Orchestrator already matched ``token`` against the open brief (H1/H2).
        lowered = (token or "").strip().lower()
        if session.stage == "pm-pe-answers":
            if "hold" in lowered:
                return
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            session.stage = "pm-pe-acked"
            await self._store.save(session)
            await self._poster.post_status(
                room,
                (
                    f"PM acknowledged PE questions for {session.initiative}. "
                    "**Next:** update PRD as needed; PE may `attest` when satisfied."
                ),
                EventType.DONE,
            )
            return
        if session.stage == "prd-merge":
            if "hold" in lowered:
                session.awaiting = AWAITING_NONE
                session.open_brief = None
                await self._store.save(session)
                await self._poster.post_status(
                    room,
                    f"Holding meta merge for {session.initiative}.",
                    EventType.PROGRESS,
                )
                return
            await self._run_merge(tenant, room, session)

    async def _on_pe_questions(self, tenant: TenantContext, room: str, baton: Baton) -> None:
        init = (baton.initiative or "").strip().upper()
        path = str((baton.payload or {}).get("questions_path") or "")
        pr_url = str((baton.payload or {}).get("pr_url") or "")
        round_n = str((baton.payload or {}).get("round") or "?")
        count = str((baton.payload or {}).get("count") or "?")
        session = AgentWorkSession(
            tenant_slug=tenant.slug,
            role_id=self.role_id,
            room=room,
            work_id=f"PEQ-{init}",
            initiative=init,
            programme=PROGRAMME_META_PM,
            stage="pm-pe-answers",
            slots={
                "pr_url": pr_url,
                "questions_path": path,
                "pe_round": round_n,
                "pe_count": count,
                "glue": "pe_questions",
            },
        )
        brief = self._briefs.build_brief(
            purpose="pm-pe-answers",
            node_id="pm-pe-answers",
            question=(
                f"PE Gate‑1 questions for {init} (round {round_n}, {count} Q). "
                "Review PR thread / Buzz, update PRD if needed, then ack."
            ),
            example="Reply on the meta PR; then `ack_pe` here when product stance is captured.",
            options=["ack_pe — PM has answered / will update PRD", "hold — need more time"],
            recommend="ack_pe",
            bluf="PE waits for product answers before attest.",
            reply_tokens=["ack_pe", "hold"],
        )
        session.open_brief = brief
        session.awaiting = AWAITING_JUDGMENT
        await self._store.save(session)
        await self._poster.post_status(
            room,
            (
                f"PM received PE questions for **{init}** "
                f"(round {round_n}, {count} Q).\n"
                f"PR: {pr_url or 'n/a'}\n"
                f"Artefact: `{path or 'n/a'}`\n"
                f"**Next:** {self._briefs.format_brief_markdown(brief)}"
            ),
            EventType.START,
        )

    async def reopen_merge_gate(
        self,
        tenant: TenantContext,
        room: str,
        *,
        initiative: str,
        pr_url: str = "",
        attestation_url: str = "",
    ) -> None:
        """Re-open Lead authorize for prd_merge (resume / retry after draft 405)."""
        await self._open_merge_gate(
            tenant,
            room,
            initiative=initiative,
            pr_url=pr_url,
            attestation=attestation_url,
        )

    async def _on_merge_ready(self, tenant: TenantContext, room: str, baton: Baton) -> None:
        init = (baton.initiative or "").strip().upper()
        pr_url = str((baton.payload or {}).get("pr_url") or "")
        attestation = str((baton.payload or {}).get("attestation_url") or "")
        await self._open_merge_gate(
            tenant, room, initiative=init, pr_url=pr_url, attestation=attestation
        )

    async def _open_merge_gate(
        self,
        tenant: TenantContext,
        room: str,
        *,
        initiative: str,
        pr_url: str,
        attestation: str,
    ) -> None:
        init = initiative.strip().upper()
        # Same work_id as initiative so bare `go ahead` / resume bind to this Gate‑1 merge.
        existing = await self._store.load(tenant.slug, self.role_id, init)
        slots = dict(existing.slots) if existing is not None else {}
        slots.update(
            {
                "pr_url": pr_url,
                "attestation_url": attestation,
                "glue": "prd_merge",
            }
        )
        session = AgentWorkSession(
            tenant_slug=tenant.slug,
            role_id=self.role_id,
            room=room,
            work_id=init,
            initiative=init,
            programme=PROGRAMME_META_PM,
            stage="prd-merge",
            slots=slots,
        )
        brief = self._briefs.build_brief(
            purpose="prd-merge",
            node_id="prd-merge",
            question=f"Authorize `prd_merge` for {init}? PE has attested.",
            example="Merges the meta PRD draft PR. App repos kick in after merge (later programmes).",
            options=["authorize prd_merge — merge now", "hold — do not merge"],
            recommend="authorize",
            bluf="Nothing merges until you authorize.",
            reply_tokens=["go ahead", "authorize prd_merge", "hold"],
        )
        session.open_brief = brief
        # Judgment (not catalogue authorize): pe_glue.after_judgment runs prd_merge.
        session.awaiting = AWAITING_JUDGMENT
        await self._store.save(session)
        await self._poster.post_status(
            room,
            (
                f"PE attested {init}. Ready for meta merge.\n"
                f"PR: {pr_url or 'n/a'}\n"
                f"Attestation: {attestation or 'n/a'}\n\n"
                + self._briefs.format_brief_markdown(brief)
            ),
            EventType.PROGRESS,
        )

    async def _run_merge(self, tenant: TenantContext, room: str, session: AgentWorkSession) -> None:
        init = (session.initiative or "").strip().upper()
        pr_url = session.slots.get("pr_url") or ""
        pr_number = _pr_number_from_url(pr_url) or _int_slot(session.slots.get("pr_number"))
        if pr_number is None:
            await self._poster.post_status(
                room,
                (
                    f"Cannot merge {init} — missing PR number. "
                    "**Next:** ensure `pr_url` / `pr_number` is on the session."
                ),
                EventType.STALL,
            )
            return
        if not forge_allowed(self.role_id, "prd_merge"):
            await self._poster.post_status(
                room, "Forge ACL denies prd_merge for adh.pm.", EventType.STALL
            )
            return
        try:
            app = self._workspace.pm_app_role()
            result = await self._forge.prd_merge(
                app=app,
                repo=tenant.meta_repo,
                pr_number=pr_number,
                commit_title=f"merge({init}): Gate‑1 attested PRD",
            )
        except Exception as exc:
            msg = str(exc)
            hint = "Reply `go ahead` to retry or `hold`."
            if "405" in msg:
                hint = (
                    "GitHub refused merge (often still a **draft** PR — "
                    "mark ready for review, then retry). " + hint
                )
            # Keep the authorize brief open for retry.
            brief = self._briefs.build_brief(
                purpose="prd-merge",
                node_id="prd-merge",
                question=f"Authorize `prd_merge` for {init}? PE has attested.",
                example="Merges the meta PRD PR after it is ready for review (not draft).",
                options=["authorize prd_merge — merge now", "hold — do not merge"],
                recommend="authorize",
                bluf="Nothing merges until you authorize.",
                reply_tokens=["go ahead", "authorize prd_merge", "hold"],
            )
            session.open_brief = brief
            session.awaiting = AWAITING_JUDGMENT
            session.stage = "prd-merge"
            await self._store.save(session)
            await self._poster.post_status(
                room,
                f"prd_merge failed for {init}: {exc}. {hint}",
                EventType.STALL,
            )
            return
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        session.stage = "prd-merged"
        session.slots["merge_sha"] = result.url or ""
        await self._store.save(session)
        await self._poster.post_status(
            room,
            (
                f"Merged `{init}` PR #{pr_number}: {result.url or 'ok'}.\n"
                f"**Next:** waiting on `adh.kb` (`kb.enrich` baton)."
            ),
            EventType.DONE,
            {"status": "prd_merged", "initiative": init, "pr": pr_number},
        )
        await self._purge_temps(tenant, room, init, PurgeEvent.PRD_MERGED)
        await self._emit_kb_enrich(tenant, room, init, pr_number)

    async def _purge_temps(
        self,
        tenant: TenantContext,
        room: str,
        initiative: str,
        event: PurgeEvent,
    ) -> None:
        listing = self._workspace.inventory(tenant)
        ctx = PurgeContext(
            initiative=initiative,
            meta_repo=tenant.meta_repo,
            candidates=tuple(listing.think_paths),
        )
        purged = execute_purge(self._workspace, tenant, event, ctx)
        if not purged:
            return
        await self._poster.post_status(
            room,
            buzz_purge_notice(event, initiative, purged),
            EventType.PROGRESS,
            {
                "status": "temps_purged",
                "event": event.value,
                "initiative": initiative,
                "paths": purged,
            },
        )

    async def _emit_kb_enrich(
        self, tenant: TenantContext, room: str, initiative: str, pr_number: int
    ) -> None:
        ttl = int(self._settings.baton_ttl_seconds)
        baton = Baton(
            type="kb.enrich",
            from_role=self.role_id,
            to_role="adh.kb",
            tenant=tenant.slug,
            ops_room=room,
            initiative=initiative,
            idempotency_key=f"kb.enrich:{tenant.slug}:{initiative}:post-merge",
            payload={
                "reason": "post_prd_merge",
                "repo_ref": tenant.meta_repo,
                "pr_number": pr_number,
            },
        )
        stored, created = await self._batons.create_pending(baton, ttl=ttl)
        notice = (
            f"baton `kb.enrich` → `adh.kb` (init={initiative}; "
            f"correlation={stored.correlation_id})"
        )
        if not created:
            notice = f"(idempotent) {notice}"
        await self._poster.post_status(
            room,
            notice,
            EventType.PROGRESS,
            {
                "status": "baton_emitted",
                "baton_type": "kb.enrich",
                "baton_id": stored.id,
                "idempotency_key": stored.idempotency_key,
                "tenant": tenant.slug,
                "initiative": initiative,
                "created": created,
            },
        )


def _pr_number_from_url(pr_url: str) -> int | None:
    """Parse trailing `/pull/N` without regex."""
    parts = (pr_url or "").rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "pull" and parts[-1].isdigit():
        return int(parts[-1])
    return None


def _int_slot(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if text.isdigit():
        return int(text)
    return None
