"""Verify wave programme — lab check → overlay up → make verify → analyze → GateOpener/collab."""

from __future__ import annotations

from injector import inject

from src.adh_agents.baton.models import Baton, BatonStatus, Rollup
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.human_replies import (
    ANOTHER_ROUND,
    HOLD,
    WAVE_ACCEPTED,
    normalize_reply,
)
from src.adh_agents.programmes.coder.roles import coder_role_for_repo, short_repo
from src.adh_agents.programmes.verify.analyze import analyze_database
from src.adh_agents.programmes.verify.gates import (
    hold_cap_brief,
    hold_cap_coach,
    wave_acceptance_brief,
    wave_acceptance_coach,
)
from src.adh_agents.programmes.verify.hermes_packs import run_rca, run_substantiate
from src.adh_agents.programmes.verify.lab import (
    discover_lab_database_url,
    lab_is_healthy,
    resolve_lab_paths,
    run_make,
)
from src.adh_agents.programmes.verify.roles import is_verify_role, verify_role
from src.adh_agents.runtime.gate_opener import GateOpener
from src.adh_agents.runtime.work_models import (
    AWAITING_NONE,
    PROGRAMME_VERIFY,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.settings import VerifyAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.business_services.buzz_service import BuzzService
from src.infra_services.prompt_service import PromptService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.models.buzz_models import EventType, MessageCreate, MessageKind, RoomMemberCreate
from src.models.tenant_models import TenantContext

_BATON_TYPE = "verify.wave"
_CODER_RETURN = "coder.wave"


class VerifyWaveProgramme(BaseBusinessService):
    """Prove tip on real lab + overlay; collaborate with Coder under round cap."""

    programme_id = PROGRAMME_VERIFY
    role_id = "adh.verify"

    @inject
    def __init__(
        self,
        store: AgentWorkStore,
        batons: RedisBatonStore,
        poster: HermesBuzzPoster,
        tenants: TenantRegistryService,
        prompts: PromptService,
        briefs: HermesBriefService,
        gates: GateOpener,
        buzz: BuzzService,
    ) -> None:
        super().__init__()
        self._store = store
        self._batons = batons
        self._poster = poster
        self._tenants = tenants
        self._prompts = prompts
        self._briefs = briefs
        self._gates = gates
        self._buzz = buzz
        self._settings = VerifyAgentSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        del tenant, room, session

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        session = await self._store.load(tenant.slug, self.role_id, work_id)
        if session is None:
            await self._poster.post_status(
                room,
                f"Verify resume: no session for `{work_id}`.",
                EventType.STALL,
                identity_handle=self.role_id,
            )
            return
        await self._open_acceptance(tenant, room, session)

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        del tenant
        return []

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        allowed = list(session.open_brief.reply_tokens) if session.open_brief else []
        matched = normalize_reply(token, allowed) or (token or "").strip().lower()
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("wave_id") or ""

        if matched in {HOLD, "park"} or "hold" in matched:
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            session.slots["verify_held"] = "true"
            await self._store.save(session)
            await self._poster.post_status(
                room,
                f"Verify parked **{init}** `{wave}` on `{repo}`.",
                EventType.PROGRESS,
                identity_handle=self.role_id,
            )
            return

        if matched == WAVE_ACCEPTED or matched == "wave-accepted":
            session.open_brief = None
            session.awaiting = AWAITING_NONE
            session.stage = "wave-awaiting-closeout"
            session.slots["verify_accepted"] = "true"
            await self._store.save(session)
            await self._emit_coder_return(
                tenant,
                room=room,
                session=session,
                stage="verify_accepted",
                findings="",
            )
            await self._poster.post_status(
                room,
                f"Verify accepted **{init}** `{wave}` — handed Coder closeout.",
                EventType.DONE,
                {"status": "verify_accepted", "initiative": init, "wave_id": wave},
                identity_handle=self.role_id,
            )
            return

        await self._poster.post_status(
            room,
            f"Verify ignored token `{token}` — reply with a listed token.",
            EventType.PROGRESS,
            identity_handle=self.role_id,
        )

    async def handle_baton(self, baton: Baton, *, room: str) -> Rollup:
        ttl = int(self._settings.baton_ttl_seconds)
        if (baton.type or "").strip() != _BATON_TYPE or not is_verify_role(baton.to_role):
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

        payload = baton.payload or {}
        init = (baton.initiative or "").strip().upper()
        repo = str(payload.get("repo") or "").strip()
        wave = str(payload.get("wave_id") or "").strip()
        collab = (baton.ops_room or "").strip() or room or tenant.ops_room
        round_n = int(payload.get("collab_round") or 1)
        max_rounds = int(self._settings.max_collab_rounds)

        session = AgentWorkSession(
            role_id=self.role_id,
            tenant_slug=tenant.slug,
            room=collab,
            work_id=f"verify:{init}:{repo}:{wave}",
            programme=PROGRAMME_VERIFY,
            stage="wave-acceptance",
            awaiting=AWAITING_NONE,
            slots={
                "initiative": init,
                "repo": repo,
                "wave_id": wave,
                "pr_url": str(payload.get("pr_url") or ""),
                "pr_number": str(payload.get("pr_number") or ""),
                "verify_command": str(payload.get("verify_command") or "make verify"),
                "compose_dir": str(payload.get("compose_dir") or ""),
                "lab_name": str(payload.get("lab_name") or self._settings.lab_root_name),
                "coverage_packet": str(payload.get("coverage_packet") or ""),
                "coder_handle": str(payload.get("coder_handle") or ""),
                "collab_round": str(round_n),
                "baton_idempotency_key": baton.idempotency_key or "",
            },
        )
        await self._store.save(session)

        ok, reason = lab_is_healthy()
        if not ok:
            await self._poster.post_status(
                collab,
                f"Verify **hold** — lab not present: {reason}",
                EventType.STALL,
                {"status": "verify_lab_missing", "reason": reason},
                identity_handle=self.role_id,
            )
            session.slots["verify_held"] = "lab_missing"
            await self._store.save(session)
            brief = hold_cap_brief(
                self._briefs,
                initiative=init,
                wave_id=wave,
                repo=repo,
                rounds=round_n,
                max_rounds=max_rounds,
                bluf=f"Shared lab not healthy: {reason}",
            )
            coach = hold_cap_coach(
                initiative=init,
                wave_id=wave,
                repo=repo,
                rounds=round_n,
                max_rounds=max_rounds,
                bluf=reason,
            )
            god_token = await self._gates.open(session, brief=brief, coach=coach)
            if god_token:
                await self.after_judgment(tenant, collab, session, god_token)
            await self._batons.mark_done(baton, ttl=ttl)
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.DONE,
                summary="lab_missing_hold",
                correlation_id=baton.correlation_id,
            )

        paths = resolve_lab_paths(
            self._tenants.workspace_root(),
            lab_name=session.slots.get("lab_name") or self._settings.lab_root_name,
            overlay_name=self._settings.default_overlay_name,
            compose_dir=session.slots.get("compose_dir") or "",
        )
        if not paths.overlay_root.is_dir():
            evidence = f"overlay missing at {paths.overlay_root}"
            await self._fail_or_collab(
                tenant,
                collab,
                session,
                baton,
                evidence=evidence,
                round_n=round_n,
                max_rounds=max_rounds,
                ttl=ttl,
            )
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.DONE,
                summary="overlay_missing",
                correlation_id=baton.correlation_id,
            )

        await self._poster.post_status(
            collab,
            f"Verify deploying overlay `{paths.overlay_root.name}` for **{init}** `{wave}`…",
            EventType.PROGRESS,
            {"status": "verify_deploy", "overlay": str(paths.overlay_root)},
            identity_handle=self.role_id,
        )
        up = run_make(paths.overlay_root, "up", timeout_seconds=900)
        if not up.ok:
            evidence = (
                f"make up failed exit={up.exit_code}\nstdout:\n{up.stdout[-4000:]}\n"
                f"stderr:\n{up.stderr[-2000:]}"
            )
            await self._fail_or_collab(
                tenant,
                collab,
                session,
                baton,
                evidence=evidence,
                round_n=round_n,
                max_rounds=max_rounds,
                ttl=ttl,
            )
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.DONE,
                summary="overlay_up_failed",
                correlation_id=baton.correlation_id,
            )

        # Trigger: prefer make verify on overlay; else make verify on product repo tip.
        verify_root = paths.overlay_root
        vcmd = (session.slots.get("verify_command") or "make verify").strip()
        if vcmd.startswith("make "):
            target = vcmd.split(maxsplit=1)[1].strip() or "verify"
        else:
            target = "verify"
        trigger = run_make(verify_root, target, timeout_seconds=600)
        db_url = discover_lab_database_url(paths.lab_root)
        analysis = await analyze_database(db_url, expect_db="realworld")

        evidence = (
            f"trigger `{trigger.command}` exit={trigger.exit_code} ok={trigger.ok}\n"
            f"stdout:\n{trigger.stdout[-3000:]}\nstderr:\n{trigger.stderr[-1500:]}\n"
            f"db: {analysis.summary}\n" + "\n".join(analysis.details)
        )
        session.slots["evidence_excerpt"] = evidence[:8000]
        await self._store.save(session)

        passed = bool(trigger.ok and analysis.ok)
        if passed:
            hermes = await run_substantiate(
                self._prompts,
                initiative=init,
                wave_id=wave,
                repo=repo,
                evidence_excerpt=evidence,
                coverage_excerpt=session.slots.get("coverage_packet") or "",
            )
            brief = wave_acceptance_brief(
                self._briefs,
                initiative=init,
                wave_id=wave,
                repo=repo,
                pr_url=session.slots.get("pr_url") or "",
                recommend=hermes.recommend,
                bluf=hermes.bluf,
                example=hermes.example,
                locking=hermes.locking,
                not_locking=hermes.not_locking,
                revise_if=hermes.revise_if,
            )
            coach = wave_acceptance_coach(
                initiative=init,
                wave_id=wave,
                repo=repo,
                pr_url=session.slots.get("pr_url") or "",
                recommend=hermes.recommend,
                bluf=hermes.bluf,
                example=hermes.example,
            )
            god_token = await self._gates.open(session, brief=brief, coach=coach)
            if god_token:
                await self.after_judgment(tenant, collab, session, god_token)
            await self._batons.mark_done(baton, ttl=ttl)
            return Rollup(
                baton_id=baton.id,
                role=self.role_id,
                status=BatonStatus.DONE,
                summary="verify_substantiate_opened",
                correlation_id=baton.correlation_id,
            )

        await self._fail_or_collab(
            tenant,
            collab,
            session,
            baton,
            evidence=evidence,
            round_n=round_n,
            max_rounds=max_rounds,
            ttl=ttl,
        )
        return Rollup(
            baton_id=baton.id,
            role=self.role_id,
            status=BatonStatus.DONE,
            summary="verify_failed_collab_or_hold",
            correlation_id=baton.correlation_id,
        )

    async def _fail_or_collab(
        self,
        tenant: TenantContext,
        room: str,
        session: AgentWorkSession,
        baton: Baton,
        *,
        evidence: str,
        round_n: int,
        max_rounds: int,
        ttl: int,
    ) -> None:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("wave_id") or ""
        hermes = await run_rca(
            self._prompts,
            initiative=init,
            wave_id=wave,
            repo=repo,
            evidence_excerpt=evidence,
            coverage_excerpt=session.slots.get("coverage_packet") or "",
        )
        if round_n >= max_rounds or hermes.recommend.lower() in {HOLD, "hold"}:
            brief = hold_cap_brief(
                self._briefs,
                initiative=init,
                wave_id=wave,
                repo=repo,
                rounds=round_n,
                max_rounds=max_rounds,
                bluf=hermes.bluf or evidence[:500],
            )
            coach = hold_cap_coach(
                initiative=init,
                wave_id=wave,
                repo=repo,
                rounds=round_n,
                max_rounds=max_rounds,
                bluf=hermes.bluf,
            )
            god_token = await self._gates.open(session, brief=brief, coach=coach)
            if god_token:
                await self.after_judgment(tenant, room, session, god_token)
            await self._batons.mark_done(baton, ttl=ttl)
            return

        # Auto collaboration — no GateOpener (2A)
        findings = hermes.bluf or evidence[:2000]
        await self._emit_coder_return(
            tenant,
            room=room,
            session=session,
            stage="verify_collab",
            findings=findings,
            next_round=round_n + 1,
        )
        await self._poster.post_status(
            room,
            (
                f"Verify collaboration → Coder **{init}** `{wave}` "
                f"(round {round_n}/{max_rounds}): {findings[:400]}"
            ),
            EventType.PROGRESS,
            {
                "status": "verify_collab",
                "round": round_n,
                "max_rounds": max_rounds,
                "recommend": hermes.recommend or ANOTHER_ROUND,
            },
            identity_handle=self.role_id,
        )
        await self._batons.mark_done(baton, ttl=ttl)

    async def _emit_coder_return(
        self,
        tenant: TenantContext,
        *,
        room: str,
        session: AgentWorkSession,
        stage: str,
        findings: str,
        next_round: int = 0,
    ) -> None:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("wave_id") or ""
        coder_handle = (session.slots.get("coder_handle") or "").strip()
        if not coder_handle:
            try:
                coder_handle = coder_role_for_repo(repo)
            except ValueError:
                coder_handle = "adh.coder"
        ttl = int(self._settings.baton_ttl_seconds)
        baton = Baton(
            type=_CODER_RETURN,
            from_role=verify_role(),
            to_role=coder_handle,
            tenant=tenant.slug,
            ops_room=room,
            initiative=init,
            idempotency_key=(
                f"{_CODER_RETURN}:{tenant.slug}:{init}:{short_repo(repo)}:"
                f"{wave}:{stage}:r{next_round or session.slots.get('collab_round') or 1}"
            ),
            payload={
                "repo": short_repo(repo),
                "wave_ids": [wave] if wave else [],
                "wave_id": wave,
                "stage": stage,
                "findings": findings,
                "pr_url": session.slots.get("pr_url") or "",
                "pr_number": session.slots.get("pr_number") or "",
                "collab_round": next_round or int(session.slots.get("collab_round") or 1),
                "verify_command": session.slots.get("verify_command") or "make verify",
                "compose_dir": session.slots.get("compose_dir") or "",
            },
        )
        stored, created = await self._batons.create_pending(baton, ttl=ttl)
        try:
            await self._buzz.ensure_member(
                RoomMemberCreate(room_slug=room, identity_handle=coder_handle)
            )
        except Exception:
            self.logger.exception("coder return member ensure failed")
        try:
            await self._buzz.post_message(
                room,
                MessageCreate(
                    identity_handle=self.role_id,
                    body=(
                        f"@{coder_handle} baton `{_CODER_RETURN}` stage=`{stage}` "
                        f"(init={init}; wave=`{wave}`; created={created})"
                    ),
                    kind=MessageKind.EVENT,
                    event_type=EventType.PROGRESS,
                    payload={
                        "status": "baton_emitted",
                        "collab": True,
                        "baton_type": _CODER_RETURN,
                        "baton_id": stored.id,
                        "idempotency_key": stored.idempotency_key,
                        "initiative": init,
                        "tenant": tenant.slug,
                        "repo": short_repo(repo),
                        "to_role": coder_handle,
                        "stage": stage,
                    },
                ),
            )
        except Exception:
            self.logger.exception("coder return notice failed")

    async def _open_acceptance(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        init = session.slots.get("initiative") or ""
        repo = session.slots.get("repo") or ""
        wave = session.slots.get("wave_id") or ""
        brief = wave_acceptance_brief(
            self._briefs,
            initiative=init,
            wave_id=wave,
            repo=repo,
            pr_url=session.slots.get("pr_url") or "",
            bluf=session.slots.get("evidence_excerpt") or "",
        )
        coach = wave_acceptance_coach(
            initiative=init,
            wave_id=wave,
            repo=repo,
            pr_url=session.slots.get("pr_url") or "",
        )
        god_token = await self._gates.open(session, brief=brief, coach=coach)
        if god_token:
            await self.after_judgment(tenant, room, session, god_token)
