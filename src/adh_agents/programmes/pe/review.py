"""PE Gate‑1 programme — claim pe.review, read fan-out, Q caps, PR+Buzz, attest."""

from __future__ import annotations

import re
from pathlib import Path

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.pe.questions import (
    build_product_questions,
    format_questions_document,
    impact_map_path,
)
from src.adh_agents.runtime.work_models import (
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    PROGRAMME_PE,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import PeAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext

_PR_NUM = re.compile(r"/pull/(\d+)")


class PeReviewProgramme(BaseBusinessService):
    programme_id = PROGRAMME_PE
    role_id = "adh.pe"

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
        self._settings = PeAgentSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        await self._poster.post_status(
            room,
            f"PE programme bound for {session.initiative or session.work_id}.",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        lowered = (token or "").strip().lower()
        if lowered in {"attest", "approve"}:
            await self._attest(tenant, room, session)
            return
        if lowered in {"new_round", "round_again"}:
            await self._post_questions(tenant, room, session, bump_round=True)
            return
        if lowered in {"hold", "await_pm"}:
            session.stage = "gate1_await_pm"
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._poster.post_status(
                room,
                f"PE holding Gate‑1 for {session.initiative} — waiting on PM answers.",
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
            await self._emit_pm_questions_baton(tenant, session)
            return
        await self._poster.post_status(
            room,
            f"PE recorded `{token}` for {session.initiative or session.work_id}.",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        live = await self._store.load(tenant.slug, self.role_id, work_id)
        if live is None:
            await self._poster.post_status(
                room,
                f"Cannot resume PE work `{work_id}` — no live session.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        await self._poster.post_status(
            room,
            f"Resuming PE work `{work_id}` at **{live.stage or 'pe'}**.",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )
        if live.stage in {"gate1_review", "gate1_questions", "gate1_await_pm"}:
            await self._post_questions(tenant, room, live, bump_round=False)

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        return []

    async def handle_baton(self, baton: Baton, *, room: str) -> Rollup:
        """Claim pe.review, fan-out read, post capped Gate‑1 questions."""
        ttl = int(self._settings.baton_ttl_seconds)
        claimed = await self._batons.claim(baton, claimant=self.role_id, ttl=ttl)
        if not claimed:
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.FAILED,
                summary="claim failed (already claimed or missing)",
                correlation_id=baton.correlation_id,
                error="claim_failed",
            )
        await self._batons.mark_running(baton, ttl=ttl)
        init = (baton.initiative or baton.id).strip().upper()
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
        pr_url = str((baton.payload or {}).get("pr_url") or "")
        session = AgentWorkSession(
            tenant_slug=baton.tenant,
            role_id=self.role_id,
            room=room or baton.ops_room,
            work_id=init,
            initiative=init if baton.initiative else None,
            programme=self.programme_id,
            stage="gate1_review",
            slots={
                "pr_url": pr_url,
                "baton_id": baton.id,
                "question_round": "0",
            },
        )
        await self._store.save(session)
        await self._poster.post_status(
            room or baton.ops_room,
            (
                f"PE claimed `pe.review` for {init}. "
                f"PR: {pr_url or 'n/a'}. "
                "Read fan-out + Gate‑1 questions next."
            ),
            EventType.START,
            {"status": "pe_claimed", "initiative": init, "baton_id": baton.id},
            identity_handle=self.role_id,
        )
        await self._emit_read_walk(tenant, baton, init, room or baton.ops_room, ttl)
        await self._post_questions(tenant, room or baton.ops_room, session, bump_round=True)
        done = await self._batons.mark_done(baton, ttl=ttl)
        return Rollup(
            baton_id=done.id,
            role=self.role_id,
            status=done.status,
            summary=f"PE Gate‑1 started for {init}; questions posted",
            correlation_id=done.correlation_id,
            artefact_refs=list(done.artefact_refs or []),
            tools_used=["baton.claim", "baton.emit_read_walk", "gate1.questions"],
        )

    async def start_gate1(
        self,
        tenant: TenantContext,
        room: str,
        *,
        initiative: str,
        pr_url: str = "",
    ) -> None:
        """Lead-triggered Gate‑1 when pe.review baton already done / missing."""
        init = initiative.strip().upper()
        session = AgentWorkSession(
            tenant_slug=tenant.slug,
            role_id=self.role_id,
            room=room,
            work_id=init,
            initiative=init,
            programme=self.programme_id,
            stage="gate1_review",
            slots={"pr_url": pr_url, "question_round": "0"},
        )
        await self._store.save(session)
        await self._poster.post_status(
            room,
            f"PE starting Gate‑1 for {init} (Lead trigger). PR: {pr_url or 'n/a'}.",
            EventType.START,
            {"status": "pe_gate1_start", "initiative": init},
            identity_handle=self.role_id,
        )
        parent = Baton(
            type="pe.review",
            from_role="adh.pm",
            to_role=self.role_id,
            tenant=tenant.slug,
            ops_room=room,
            initiative=init,
            idempotency_key=f"pe.review:{tenant.slug}:{init}:lead-trigger",
            payload={"pr_url": pr_url, "stage": "gate1_review"},
        )
        ttl = int(self._settings.baton_ttl_seconds)
        await self._emit_read_walk(tenant, parent, init, room, ttl)
        await self._post_questions(tenant, room, session, bump_round=True)

    async def _emit_read_walk(
        self,
        tenant: TenantContext,
        parent: Baton,
        init: str,
        room: str,
        ttl: int,
    ) -> None:
        repo_ref = tenant.meta_repo
        walk = Baton(
            type="read.walk",
            from_role=self.role_id,
            to_role="adh.read",
            tenant=parent.tenant,
            ops_room=parent.ops_room or room,
            initiative=init,
            idempotency_key=f"read.walk:{parent.tenant}:{init}:{repo_ref}",
            payload={
                "repo_ref": repo_ref,
                "reason": "gate1_pe_review",
                "parent_baton": parent.id,
            },
            artefact_refs=list(parent.artefact_refs or []),
        )
        stored_walk, created = await self._batons.create_pending(walk, ttl=ttl)
        notice = (
            f"baton `read.walk` → `adh.read` (init={init}; "
            f"correlation={stored_walk.correlation_id})"
        )
        if not created:
            notice = f"(idempotent) {notice}"
        await self._poster.post_status(
            room,
            notice,
            EventType.PROGRESS,
            {
                "status": "baton_emitted",
                "baton_type": "read.walk",
                "baton_id": stored_walk.id,
                "idempotency_key": stored_walk.idempotency_key,
                "initiative": init,
                "tenant": parent.tenant,
                "created": created,
            },
            identity_handle=self.role_id,
        )

    async def _post_questions(
        self,
        tenant: TenantContext,
        room: str,
        session: AgentWorkSession,
        *,
        bump_round: bool,
    ) -> None:
        init = (session.initiative or session.work_id).strip().upper()
        max_q = int(self._settings.max_product_questions)
        max_rounds = int(self._settings.max_question_rounds)
        round_n = int(session.slots.get("question_round") or "0")
        if bump_round:
            round_n += 1
        if round_n > max_rounds:
            session.stage = "gate1_exhausted"
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._poster.post_status(
                room,
                (
                    f"Gate‑1 question budget exhausted for {init} "
                    f"({max_rounds} rounds × ≤{max_q} Q). Hold — revise PRD or stop."
                ),
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return

        meta_root = Path(tenant.meta_root).expanduser()
        map_path = impact_map_path(meta_root, init)
        map_text = map_path.read_text(encoding="utf-8") if map_path.is_file() else ""
        questions = build_product_questions(map_text, initiative=init, max_questions=max_q)
        pr_url = session.slots.get("pr_url") or ""
        doc = format_questions_document(
            initiative=init,
            pr_url=pr_url,
            round_number=round_n,
            max_rounds=max_rounds,
            questions=questions,
        )
        rel = f"prd/reports/PE-Product-Questions-{init}.md"
        out = meta_root / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc, encoding="utf-8")

        session.slots["question_round"] = str(round_n)
        session.slots["questions_path"] = rel
        session.slots["question_count"] = str(len(questions))
        session.stage = "gate1_questions"
        await self._store.save(session)

        await self._poster.post_status(
            room,
            (
                f"Gate‑1 questions for {init} "
                f"(round {round_n}/{max_rounds}, {len(questions)} Q ≤{max_q}).\n\n" + doc
            ),
            EventType.PROGRESS,
            {
                "status": "gate1_questions",
                "initiative": init,
                "round": round_n,
                "count": len(questions),
            },
            identity_handle=self.role_id,
        )

        pr_number = _pr_number(pr_url)
        comment_url = ""
        if pr_number is not None and forge_allowed(self.role_id, "comment_pr"):
            try:
                app = self._workspace.app_role(self._settings.reviewer_app_slug)
                result = await self._forge.comment_pr(
                    app=app,
                    repo=tenant.meta_repo,
                    pr_number=pr_number,
                    body=doc,
                )
                comment_url = result.url or ""
                session.slots["pr_comment_url"] = comment_url
                await self._store.save(session)
                await self._poster.post_status(
                    room,
                    f"Posted Gate‑1 questions on meta PR #{pr_number}: {comment_url or 'ok'}",
                    EventType.DONE,
                    identity_handle=self.role_id,
                )
            except Exception as exc:
                await self._poster.post_status(
                    room,
                    f"PR comment failed for {init}: {exc}. Questions remain on Buzz + `{rel}`.",
                    EventType.STALL,
                    identity_handle=self.role_id,
                )

        await self._emit_pm_questions_baton(tenant, session)
        brief = self._briefs.build_brief(
            purpose="gate1-pe-next",
            node_id="gate1-pe-next",
            question=(
                f"Gate‑1 round {round_n}/{max_rounds} for {init}: wait for PM, "
                "run another capped round, or attest this head?"
            ),
            example="PM answers on PR/Buzz; PE attests only when product stance is clear.",
            options=[
                "await_pm — wait for PM answers",
                "new_round — another capped question pass",
                "attest — Approve this meta PR head (PE attestation)",
                "hold — park Gate‑1",
            ],
            recommend="await_pm",
            bluf="Attest only when satisfied; merge stays a separate PM authorize.",
            reply_tokens=["await_pm", "new_round", "attest", "hold"],
        )
        session.open_brief = brief
        session.awaiting = AWAITING_JUDGMENT
        session.stage = "gate1_await_pm"
        await self._store.save(session)
        await self._poster.post_status(
            room,
            self._briefs.format_brief_markdown(brief),
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

    async def _attest(self, tenant: TenantContext, room: str, session: AgentWorkSession) -> None:
        init = (session.initiative or session.work_id).strip().upper()
        pr_url = session.slots.get("pr_url") or ""
        pr_number = _pr_number(pr_url)
        if pr_number is None:
            await self._poster.post_status(
                room,
                f"Cannot attest {init} — no meta PR number in session.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        if not forge_allowed(self.role_id, "approve_attestation"):
            await self._poster.post_status(
                room,
                "Forge ACL denies approve_attestation for adh.pe.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        body = (
            f"Gate‑1 attestation for `{init}` by adh.pe.\n\n"
            f"Questions round: {session.slots.get('question_round') or '?'} / "
            f"{self._settings.max_question_rounds}; "
            f"count: {session.slots.get('question_count') or '?'}.\n"
            "Effective approval is for the exact current meta PR head SHA."
        )
        try:
            app = self._workspace.app_role(self._settings.reviewer_app_slug)
            # Draft PRs cannot receive APPROVE — mark ready first when needed.
            if forge_allowed(self.role_id, "ready_for_review"):
                try:
                    await self._forge.ready_for_review(
                        app=app, repo=tenant.meta_repo, pr_number=pr_number
                    )
                except Exception:
                    pass
            result = await self._forge.approve_attestation(
                app=app,
                repo=tenant.meta_repo,
                pr_number=pr_number,
                body=body,
            )
        except Exception as exc:
            await self._poster.post_status(
                room,
                f"Attest failed for {init}: {exc}. Reply `attest` to retry or `hold`.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        session.stage = "gate1_attested"
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        session.slots["attestation_url"] = result.url or ""
        await self._store.save(session)
        await self._poster.post_status(
            room,
            f"PE attested `{init}` on PR #{pr_number}: {result.url or 'ok'}. PM may authorize merge.",
            EventType.DONE,
            {
                "status": "pe_attested",
                "initiative": init,
                "pr_number": pr_number,
                "url": result.url or "",
            },
            identity_handle=self.role_id,
        )
        await self._emit_pm_merge_ready_baton(tenant, session)

    async def _emit_pm_questions_baton(
        self, tenant: TenantContext, session: AgentWorkSession
    ) -> None:
        init = (session.initiative or session.work_id).strip().upper()
        ttl = int(self._settings.baton_ttl_seconds)
        baton = Baton(
            type="pm.pe_questions",
            from_role=self.role_id,
            to_role="adh.pm",
            tenant=tenant.slug,
            ops_room=tenant.ops_room,
            initiative=init,
            idempotency_key=(
                f"pm.pe_questions:{tenant.slug}:{init}:r{session.slots.get('question_round') or '0'}"
            ),
            payload={
                "pr_url": session.slots.get("pr_url") or "",
                "questions_path": session.slots.get("questions_path") or "",
                "round": session.slots.get("question_round") or "0",
                "count": session.slots.get("question_count") or "0",
            },
            artefact_refs=[session.slots.get("questions_path") or ""],
        )
        stored, created = await self._batons.create_pending(baton, ttl=ttl)
        notice = (
            f"baton `pm.pe_questions` → `adh.pm` (init={init}; "
            f"correlation={stored.correlation_id})"
        )
        if not created:
            notice = f"(idempotent) {notice}"
        await self._poster.post_status(
            tenant.ops_room,
            notice,
            EventType.PROGRESS,
            {
                "status": "baton_emitted",
                "baton_type": "pm.pe_questions",
                "baton_id": stored.id,
                "idempotency_key": stored.idempotency_key,
                "initiative": init,
                "tenant": tenant.slug,
                "created": created,
            },
            identity_handle=self.role_id,
        )

    async def _emit_pm_merge_ready_baton(
        self, tenant: TenantContext, session: AgentWorkSession
    ) -> None:
        init = (session.initiative or session.work_id).strip().upper()
        ttl = int(self._settings.baton_ttl_seconds)
        baton = Baton(
            type="pm.prd_merge_ready",
            from_role=self.role_id,
            to_role="adh.pm",
            tenant=tenant.slug,
            ops_room=tenant.ops_room,
            initiative=init,
            idempotency_key=f"pm.prd_merge_ready:{tenant.slug}:{init}",
            payload={
                "pr_url": session.slots.get("pr_url") or "",
                "attestation_url": session.slots.get("attestation_url") or "",
            },
        )
        stored, created = await self._batons.create_pending(baton, ttl=ttl)
        notice = (
            f"baton `pm.prd_merge_ready` → `adh.pm` (init={init}; "
            f"correlation={stored.correlation_id})"
        )
        if not created:
            notice = f"(idempotent) {notice}"
        await self._poster.post_status(
            tenant.ops_room,
            notice,
            EventType.PROGRESS,
            {
                "status": "baton_emitted",
                "baton_type": "pm.prd_merge_ready",
                "baton_id": stored.id,
                "idempotency_key": stored.idempotency_key,
                "initiative": init,
                "tenant": tenant.slug,
                "created": created,
            },
            identity_handle=self.role_id,
        )


def _pr_number(pr_url: str) -> int | None:
    match = _PR_NUM.search(pr_url or "")
    if not match:
        return None
    return int(match.group(1))
