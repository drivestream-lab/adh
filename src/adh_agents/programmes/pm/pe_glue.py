"""PM glue for product questions + authorize product merge after PE attest."""

from __future__ import annotations

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.gate_coach import TokenAction
from src.adh_agents.collaboration.human_replies import (
    MERGE_PRODUCT_PR,
    PARK,
    merge_gate_tokens,
    merge_gate_wills,
    tokens_equivalent,
)
from src.adh_agents.collaboration.temp_papers import (
    PurgeContext,
    PurgeEvent,
    buzz_purge_notice,
    execute_purge,
)
from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.pm.pe_answers import PmPeAnswersProgramme
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
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext


class PmPeGlueProgramme(BaseBusinessService):
    """pm.pe_questions → auto-answers; pm.prd_merge_ready → human merge coach (U6)."""

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
        pe_answers: PmPeAnswersProgramme,
    ) -> None:
        super().__init__()
        self._store = store
        self._batons = batons
        self._poster = poster
        self._briefs = briefs
        self._forge = forge
        self._workspace = workspace
        self._tenants = tenants
        self._pe_answers = pe_answers
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
        # U6: no mid-rally ack_pe gate — only merge / park / discard-local.
        lowered = (token or "").strip().lower()
        if session.stage == "prd-merge":
            if tokens_equivalent(token, PARK):
                session.awaiting = AWAITING_NONE
                session.open_brief = None
                await self._store.save(session)
                await self._poster.post_status(
                    room,
                    f"Holding product merge for {session.initiative}.",
                    EventType.PROGRESS,
                )
                return
            if "discard local" in lowered:
                await self._discard_local_and_retry(tenant, room, session)
                return
            await self._run_merge(tenant, room, session)

    async def _on_pe_questions(self, tenant: TenantContext, room: str, baton: Baton) -> None:
        """U6: agent auto-answers — never open a human ack gate."""
        await self._pe_answers.answer_pe_questions(tenant, room, baton)

    async def reopen_merge_gate(
        self,
        tenant: TenantContext,
        room: str,
        *,
        initiative: str,
        pr_url: str = "",
        attestation_url: str = "",
    ) -> None:
        """Re-open Lead authorize for product merge (resume / retry after draft 405)."""
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
        # Same work_id as initiative so bare `go ahead` / resume bind to this product merge.
        existing = await self._store.load(tenant.slug, self.role_id, init)
        slots = dict(existing.slots) if existing is not None else {}
        slots.update(
            {
                "pr_url": pr_url,
                "attestation_url": attestation,
                "glue": "prd_merge",
            }
        )
        pr_number = _pr_number_from_url(pr_url) or _int_slot(slots.get("pr_number"))
        if pr_number is not None:
            slots["pr_number"] = str(pr_number)
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
        wills = merge_gate_wills()
        brief = self._briefs.build_brief(
            purpose="prd-merge",
            node_id="prd-merge",
            question=(
                f"Clarifications settled for {init}. "
                "Review the briefs outside ADH, then merge the product PR?"
            ),
            example="I will undraft + merge the product PR, then refresh local develop.",
            options=[
                f"{MERGE_PRODUCT_PR} — land into develop now",
                f"{PARK} — do not merge",
            ],
            recommend=MERGE_PRODUCT_PR,
            bluf="Army finished the PE↔PM rally and PE attested — your call to land.",
            reply_tokens=merge_gate_tokens(),
        )
        session.open_brief = brief
        # Judgment (not catalogue authorize): pe_glue.after_judgment runs product merge.
        session.awaiting = AWAITING_JUDGMENT
        await self._store.save(session)
        evidence_bits = [
            b
            for b in (
                f"PR: {pr_url}" if pr_url else "",
                f"Attestation: {attestation}" if attestation else "",
            )
            if b
        ]
        await self._poster.post_human_next(
            room,
            i_did=(
                f"Clarifications settled for **{init}**. "
                "PE attested the product PR head after the agent↔agent rally."
            ),
            recommend=MERGE_PRODUCT_PR,
            recommend_why="Review the question/answer briefs, then land when product stance looks right.",
            evidence=" · ".join(evidence_bits) if evidence_bits else "",
            outside_adh=(
                "Read the product PR thread (PE questions + PM answers), the product brief, "
                "and attestation in GitHub / Cursor. Do **not** merge on GitHub yourself."
            ),
            tokens=[TokenAction(tok, wills.get(tok, "continue")) for tok in merge_gate_tokens()],
            hop="clarifications_settled",
            payload={
                "status": "need_prd_merge",
                "initiative": init,
                "purpose": "prd-merge",
                "pr_number": pr_number,
            },
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
                room, "Forge ACL denies product merge for adh.pm.", EventType.STALL
            )
            return
        try:
            app = self._workspace.pm_app_role()
            result = await self._forge.land_pull_request(
                app=app,
                repo=tenant.meta_repo,
                pr_number=pr_number,
                commit_title=f"merge({init}): product PR attested",
            )
        except Exception as exc:
            await self._reopen_merge_stall(tenant, room, session, init, exc)
            return

        try:
            sync = self._workspace.sync_integration_branch(tenant)
        except ValidationError as exc:
            session.awaiting = AWAITING_JUDGMENT
            session.stage = "prd-merge"
            session.slots["merge_sha"] = result.url or ""
            session.slots["sync_stall"] = "dirty"
            brief = self._briefs.build_brief(
                purpose="prd-merge",
                node_id="prd-merge",
                question=(
                    f"Product PR #{pr_number} merged for {init}, but local meta is dirty. "
                    "Discard local changes so I can sync develop?"
                ),
                example="I will not silently overwrite dirty local meta.",
                options=[
                    "discard local — reset local meta to origin develop",
                    "hold — leave local as-is",
                ],
                recommend="discard local",
                bluf="Remote is landed; local meta must match before KB continues cleanly.",
                reply_tokens=["discard local", "hold"],
            )
            session.open_brief = brief
            await self._store.save(session)
            await self._poster.post_human_next(
                room,
                i_did=f"Merged product PR #{pr_number} for **{init}**, but local meta is dirty.",
                recommend="discard local",
                recommend_why=str(exc),
                evidence=f"PR #{pr_number}" + (f" · {result.url}" if result.url else ""),
                outside_adh="Inspect local meta dirty files in Cursor before discarding.",
                tokens=[
                    TokenAction(
                        "discard local",
                        "hard-reset local meta to origin develop, purge, hand off to KB",
                    ),
                    TokenAction("hold", "leave local dirty — KB baton not emitted yet"),
                ],
                hop="prd-merge",
                event_type=EventType.STALL,
                payload={"status": "sync_stall", "initiative": init, "pr": pr_number},
            )
            return

        session.awaiting = AWAITING_NONE
        session.open_brief = None
        session.stage = "prd-merged"
        session.slots["merge_sha"] = result.url or ""
        session.slots["sync_sha"] = sync.get("sha") or ""
        await self._store.save(session)
        await self._poster.post_status(
            room,
            (
                f"Landed product PR #{pr_number} for **{init}** "
                f"(local develop synced to `{sync.get('sha') or 'origin'}`).\n"
                f"**Next:** waiting on KB for knowledge docs."
            ),
            EventType.DONE,
            {"status": "prd_merged", "initiative": init, "pr": pr_number},
        )
        await self._purge_temps(tenant, room, init, PurgeEvent.PRD_MERGED)
        await self._emit_kb_enrich(tenant, room, init, pr_number)

    async def _discard_local_and_retry(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = (session.initiative or "").strip().upper()
        pr_number = _int_slot(session.slots.get("pr_number")) or _pr_number_from_url(
            session.slots.get("pr_url") or ""
        )
        try:
            sync = self._workspace.sync_integration_branch(tenant, force=True)
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Could not discard/sync local meta for {init}: {exc}",
                EventType.STALL,
            )
            return
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        session.stage = "prd-merged"
        session.slots["sync_sha"] = sync.get("sha") or ""
        session.slots.pop("sync_stall", None)
        await self._store.save(session)
        await self._poster.post_status(
            room,
            (
                f"Local develop synced for **{init}** "
                f"(`{sync.get('sha') or 'origin'}`). Handing off to KB."
            ),
            EventType.DONE,
            {"status": "prd_merged", "initiative": init, "pr": pr_number},
        )
        await self._purge_temps(tenant, room, init, PurgeEvent.PRD_MERGED)
        if pr_number is not None:
            await self._emit_kb_enrich(tenant, room, init, pr_number)

    async def _reopen_merge_stall(
        self,
        tenant: TenantContext,
        room: str,
        session: AgentWorkSession,
        init: str,
        exc: Exception,
    ) -> None:
        del tenant  # brief reopen only
        msg = str(exc)
        wills = merge_gate_wills()
        hint = f"Reply `{MERGE_PRODUCT_PR}` to retry or `{PARK}`."
        if "405" in msg:
            hint = (
                "GitHub refused merge (often still a draft — I undraft first; "
                "if this persists, check branch protection). " + hint
            )
        brief = self._briefs.build_brief(
            purpose="prd-merge",
            node_id="prd-merge",
            question=f"Retry product merge for {init}? PE has attested.",
            example="I will undraft + merge the product PR after it is ready.",
            options=[
                f"{MERGE_PRODUCT_PR} — merge now",
                f"{PARK} — do not merge",
            ],
            recommend=MERGE_PRODUCT_PR,
            bluf="Nothing merges until you authorize.",
            reply_tokens=merge_gate_tokens(),
        )
        session.open_brief = brief
        session.awaiting = AWAITING_JUDGMENT
        session.stage = "prd-merge"
        await self._store.save(session)
        await self._poster.post_human_next(
            room,
            i_did=f"Tried to land the product PR for **{init}** and hit an error.",
            recommend=MERGE_PRODUCT_PR,
            recommend_why=f"{exc}. {hint}",
            outside_adh="Check the product PR status on GitHub / Cursor, then retry here.",
            tokens=[TokenAction(tok, wills.get(tok, "continue")) for tok in merge_gate_tokens()],
            hop="clarifications_settled",
            event_type=EventType.STALL,
            payload={"status": "prd_merge_failed", "initiative": init},
        )

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
        if not created:
            self.logger.info(
                "kb.enrich baton idempotent (no Buzz)",
                baton_id=stored.id,
                initiative=initiative,
            )
            return
        await self._poster.post_status(
            room,
            (
                f"baton `kb.enrich` → `adh.kb` (init={initiative}; "
                f"correlation={stored.correlation_id})"
            ),
            EventType.PROGRESS,
            {
                "status": "baton_emitted",
                "baton_type": "kb.enrich",
                "baton_id": stored.id,
                "idempotency_key": stored.idempotency_key,
                "tenant": tenant.slug,
                "initiative": initiative,
                "created": True,
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
