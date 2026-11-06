"""meta-pm programme: catalogue skills + Lead briefs (replaces post_promote_walk)."""

from __future__ import annotations

import json
from typing import Any, Optional

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.hermes.collaboration.brief_service import HermesBriefService
from src.business_services.hermes.decision_card import (
    CARD_POSTPM,
    DecisionCard,
    decision_card,
    parse_postpm_decision_card,
)
from src.business_services.hermes.decision_cards import apply_validate_briefs
from src.business_services.hermes.execution.dispatch_service import HermesDispatchService
from src.business_services.hermes.runtime.navigator_service import HermesNavigatorService
from src.business_services.hermes.runtime.session_store import HermesSessionStoreService
from src.business_services.hermes.surface.buzz_poster import HermesBuzzPoster
from src.business_services.hermes.validation_report import (
    format_resolution_markdown,
    impact_map_path,
    open_critical,
    parse_validation_findings,
    resolution_path,
    validation_report_path,
)
from src.configs.hermes_settings import HermesSettings
from src.infra_services.pm_workspace_service import (
    PmWorkspaceService,
    hermes_post_pm_brief_path,
    prd_path,
)
from src.infra_services.prompt_service import PromptService
from src.models.buzz_models import EventType
from src.models.hermes.session_models import (
    AWAITING_AUTHORIZATION,
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    HermesProgrammeType,
    HermesSession,
)
from src.models.tenant_models import TenantContext

_SLOT_FINDINGS = "meta_pm_findings"
_SLOT_DECISIONS = "meta_pm_decisions"
_SLOT_WAVE = "meta_pm_wave"
_SLOT_VALIDATE_PASS = "meta_pm_validate_pass"
_PROGRAMME = HermesProgrammeType.META_PM


def _format_findings_for_judge(wave: list[dict[str, Any]]) -> str:
    """Readable frozen findings for the validate PM card (not raw JSON alone)."""
    blocks: list[str] = []
    for row in wave:
        fid = str(row.get("id") or "?")
        blocks.append(
            "\n".join(
                [
                    f"### {fid}",
                    f"severity: {row.get('severity') or ''}",
                    f"location: {row.get('location') or ''}",
                    f"finding: {row.get('finding') or ''}",
                    f"validator_recommendation: {row.get('recommendation') or ''}",
                ]
            )
        )
    return "\n\n".join(blocks) if blocks else "(none)"


class MetaPmProgrammeService(BaseBusinessService):
    """Walk meta-pm from the catalogue entrypoint with session-backed gates."""

    @inject
    def __init__(
        self,
        store: HermesSessionStoreService,
        dispatch: HermesDispatchService,
        briefs: HermesBriefService,
        navigator: HermesNavigatorService,
        poster: HermesBuzzPoster,
        workspace: PmWorkspaceService,
        prompts: PromptService,
    ) -> None:
        super().__init__()
        self._store = store
        self._dispatch = dispatch
        self._briefs = briefs
        self._navigator = navigator
        self._poster = poster
        self._workspace = workspace
        self._prompts = prompts
        self._settings = HermesSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: HermesSession
    ) -> None:
        initiative = (session.initiative or "").strip()
        if not initiative:
            await self._poster.post_status(
                room,
                "meta-pm needs an initiative id before skills run.",
                EventType.STALL,
            )
            return
        dest = prd_path(initiative)
        body = self._workspace.read_local(tenant, dest)
        if not (body or "").strip():
            await self._poster.post_status(
                room,
                f"Missing promoted PRD `{dest}` for {initiative}. Promote a think file first.",
                EventType.STALL,
                {"status": "post_pm_missing_prd", "initiative": initiative, "path": dest},
            )
            return
        session.programme = _PROGRAMME
        session.room = room
        await self._store.save(session)
        await self._run_validate_cycle(tenant, room, session, pass_number=1)

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]:
        """Artefact-backed recovery candidates: initiative + gate label."""
        listing = self._workspace.inventory(tenant)
        rows: list[dict[str, str]] = []
        for init in listing.inits:
            impact = (self._workspace.read_local(tenant, impact_map_path(init)) or "").strip()
            if impact:
                rows.append(
                    {
                        "initiative": init,
                        "gate": "authorize",
                        "hint": f"{init} — draft-PR authorize (Impact-Map present)",
                    }
                )
                continue
            post_pm = (
                self._workspace.read_local(tenant, hermes_post_pm_brief_path(init)) or ""
            ).strip()
            if post_pm:
                rows.append(
                    {
                        "initiative": init,
                        "gate": "post-pm-confirm",
                        "hint": f"{init} — post-PM confirm/revise",
                    }
                )
                continue
            prd = (self._workspace.read_local(tenant, prd_path(init)) or "").strip()
            if prd:
                rows.append(
                    {
                        "initiative": init,
                        "gate": "validate",
                        "hint": f"{init} — post-pm / validate (PRD present)",
                    }
                )
        return rows

    async def resume_programme(self, tenant: TenantContext, room: str, initiative: str) -> None:
        """Rebuild the latest human gate from local artefacts after session TTL loss.

        Prefer: Impact-Map → draft-PR authorize; else post-PM brief → confirm/revise;
        else promoted PRD → start validate (same as ``post-pm`` once INIT is bound).
        """
        init = (initiative or "").strip().upper()
        if not init:
            await self._poster.post_status(
                room,
                "Which initiative should I resume? Reply with the programme initiative id.",
                EventType.STALL,
            )
            return
        session = HermesSession(
            tenant_slug=tenant.slug,
            room=room,
            initiative=init,
            programme=_PROGRAMME,
        )
        impact_body = (self._workspace.read_local(tenant, impact_map_path(init)) or "").strip()
        post_pm_body = (
            self._workspace.read_local(tenant, hermes_post_pm_brief_path(init)) or ""
        ).strip()
        prd_body = (self._workspace.read_local(tenant, prd_path(init)) or "").strip()

        if impact_body:
            await self._poster.post_status(
                room,
                (
                    f"Resuming {init} at **draft-PR authorize** "
                    f"(found `{impact_map_path(init)}`)."
                ),
                EventType.PROGRESS,
                {"status": "resume_authorize", "initiative": init},
            )
            await self._open_forge_auth(tenant, room, session)
            return

        if post_pm_body:
            await self._poster.post_status(
                room,
                (
                    f"Resuming {init} at **post-PM confirm** "
                    f"(found `{hermes_post_pm_brief_path(init)}`). "
                    "Reply `confirm` or `revise`."
                ),
                EventType.PROGRESS,
                {"status": "resume_post_pm", "initiative": init},
            )
            await self._reopen_post_pm_brief(tenant, room, session)
            return

        if prd_body:
            await self._poster.post_status(
                room,
                (
                    f"Resuming {init} via **post-pm / validate** "
                    f"(PRD present; no post-PM brief or Impact-Map yet)."
                ),
                EventType.PROGRESS,
                {"status": "resume_validate", "initiative": init},
            )
            await self.start_programme(tenant, room, session)
            return

        await self._poster.post_status(
            room,
            (
                f"Cannot resume {init} — missing PRD (`{prd_path(init)}`). "
                "Promote a think file first, or start a new outline."
            ),
            EventType.STALL,
            {"status": "resume_missing_prd", "initiative": init},
        )

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: HermesSession, token: str
    ) -> None:
        """Continue after Lead answered an open brief."""
        stage = session.stage
        if stage == "requirements-human-decision" or stage == "validate-requirements":
            await self._apply_vf_token(tenant, room, session, token)
            return
        if stage == "prd-impact-acceptance":
            await self._after_post_pm_brief(tenant, room, session, token)
            return
        if stage == "prd-pr-action":
            # Authorization replies are handled by the orchestrator; judgment
            # tokens here are unexpected — surface and stay.
            await self._poster.post_status(
                room,
                f"Recorded `{token}` at forge gate — reply authorize tokens on the open brief.",
                EventType.PROGRESS,
            )
            return
        # Manifest-style gate stored on session while stage is update-documents
        if stage == "update-documents":
            await self._after_manifest(tenant, room, session, token)
            return
        await self._poster.post_status(
            room,
            f"Recorded `{token}` at stage `{stage}` — no further meta-pm hop wired yet.",
            EventType.PROGRESS,
        )

    async def _run_validate_cycle(
        self,
        tenant: TenantContext,
        room: str,
        session: HermesSession,
        *,
        pass_number: int,
    ) -> None:
        initiative = session.initiative or ""
        max_post = int(self._settings.pm_max_post_validate_passes)
        if pass_number > max_post:
            await self._poster.post_status(
                room,
                (
                    f"Post-PM validate budget exhausted for {initiative} "
                    f"({max_post}/{max_post}). Writing Hermes post-PM brief for Lead "
                    "(impact-map waits for Lead after confirm)."
                ),
                EventType.STALL,
            )
            await self._write_post_pm_brief(tenant, room, session)
            return
        session.stage = "validate-requirements"
        session.slots[_SLOT_VALIDATE_PASS] = str(pass_number)
        await self._store.save(session)
        interval = int(self._settings.progress_seconds)
        await self._poster.post_status(
            room,
            (
                f"Running `/validate-requirements` for {initiative} "
                f"(pass {pass_number}/{max_post}; progress every {interval}s)…"
            ),
            EventType.PROGRESS,
            {
                "status": "in_progress",
                "hop": "validate",
                "initiative": initiative,
                "pass": pass_number,
                "max_passes": max_post,
            },
        )
        try:
            result = await self._dispatch.run_skill_node(
                tenant,
                "validate-requirements",
                initiative,
                on_progress=self._poster.still_working_callback(
                    room,
                    hop="validate-requirements",
                    initiative=initiative,
                    label=f"validate pass {pass_number}",
                ),
            )
        except Exception as exc:
            self.logger.exception("validate skill failed", initiative=initiative)
            await self._poster.post_status(
                room,
                f"Validate failed for {initiative}: {str(exc)[:200]}",
                EventType.STALL,
            )
            return
        if not result.ok:
            await self._poster.post_status(
                room,
                f"Validate exited {result.exit_code} for {initiative}.",
                EventType.STALL,
            )
            return
        report = self._workspace.read_local(tenant, validation_report_path(initiative))
        if not report.strip():
            await self._poster.post_status(
                room,
                f"Empty validation report for {initiative}.",
                EventType.STALL,
            )
            return
        findings = parse_validation_findings(report)
        if not findings:
            await self._poster.post_status(
                room,
                (
                    f"Zero findings for {initiative} (pass {pass_number}/{max_post}) — "
                    "writing Hermes post-PM brief for Lead."
                ),
                EventType.PROGRESS,
            )
            await self._write_post_pm_brief(tenant, room, session)
            return
        if not open_critical(findings) and pass_number > 1:
            await self._poster.post_status(
                room,
                (
                    f"No open Critical findings for {initiative} after pass "
                    f"{pass_number} — writing Hermes post-PM brief for Lead."
                ),
                EventType.PROGRESS,
            )
            await self._write_post_pm_brief(tenant, room, session)
            return
        await self._open_vf_wave(tenant, room, session, findings, pass_number=pass_number)

    async def _open_vf_wave(
        self,
        tenant: TenantContext,
        room: str,
        session: HermesSession,
        findings: list[dict[str, Any]],
        *,
        pass_number: int = 1,
        prior: Optional[dict[str, str]] = None,
    ) -> None:
        initiative = session.initiative or ""
        decisions = dict(prior or {})
        unanswered = [row for row in findings if str(row.get("id") or "") not in decisions]
        if not unanswered:
            await self._finish_findings(tenant, room, session, findings, decisions)
            return
        limit = int(self._settings.pm_max_validate_briefs)
        wave_raw = unanswered[:limit]
        briefs = await self._build_validate_briefs(initiative, wave_raw)
        session.slots[_SLOT_FINDINGS] = json.dumps(findings)
        session.slots[_SLOT_DECISIONS] = json.dumps(decisions)
        session.slots[_SLOT_WAVE] = json.dumps(briefs)
        session.slots[_SLOT_VALIDATE_PASS] = str(pass_number)

        blocks: list[str] = []
        for item in briefs:
            brief = self._briefs.brief_from_validate_finding(
                item,
                node_id="requirements-human-decision",
                purpose="requirements-clarification",
            )
            blocks.append(self._briefs.format_brief_markdown(brief))

        auto_decide = pass_number <= int(self._settings.pm_auto_decide_validate_passes)
        if auto_decide:
            for item in briefs:
                fid = str(item.get("id") or "")
                if fid:
                    decisions[fid] = str(item.get("recommend") or "fix").strip().lower()
            session.slots[_SLOT_DECISIONS] = json.dumps(decisions)
            session.stage = "requirements-human-decision"
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            decided = ", ".join(f"`{item.get('id')}`→`{item.get('recommend')}`" for item in briefs)
            body = (
                f"**Hermes decided** (validate pass {pass_number}) — {decided}.\n\n"
                + "\n\n".join(blocks)
                + "\n\nApplying these decisions and continuing to update-documents…"
            )
            await self._poster.post_status(
                room,
                body,
                EventType.PROGRESS,
                {
                    "status": "hermes_validate_decided",
                    "initiative": initiative,
                    "pass": pass_number,
                    "decisions": {
                        str(item.get("id")): str(item.get("recommend")) for item in briefs
                    },
                },
            )
            still_open = [row for row in findings if str(row.get("id") or "") not in decisions]
            if still_open:
                await self._open_vf_wave(
                    tenant,
                    room,
                    session,
                    findings,
                    pass_number=pass_number,
                    prior=decisions,
                )
                return
            await self._finish_findings(tenant, room, session, findings, decisions)
            return

        # Later passes: Lead owns the findings checkpoint.
        reply_tokens: list[str] = ["accept-recs"]
        for item in briefs:
            brief = self._briefs.brief_from_validate_finding(
                item,
                node_id="requirements-human-decision",
                purpose="requirements-clarification",
            )
            reply_tokens.extend(brief.reply_tokens)
            reply_tokens.append(f"{item.get('id')}: explain")
        session.stage = "requirements-human-decision"
        session.open_brief = self._briefs.build_brief(
            purpose="requirements-clarification",
            node_id="requirements-human-decision",
            question=f"Decide open validation findings for {initiative}.",
            example="Each VF card below is a product call before update/impact.",
            options=[],
            recommend="accept-recs",
            recommend_why="Accept Hermes recommendations for this wave when they match your intent.",
            reply_tokens=reply_tokens,
            artefact_path=validation_report_path(initiative),
        )
        session.awaiting = AWAITING_JUDGMENT
        await self._store.save(session)
        body = "\n\n".join(blocks) + "\n\nOr `accept-recs` for this wave only."
        await self._poster.post_status(
            room,
            body,
            EventType.PROGRESS,
            {
                "status": "need_validate_decisions",
                "initiative": initiative,
                "choices": [item.get("id") for item in briefs],
            },
        )

    async def _build_validate_briefs(
        self, initiative: str, wave: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        try:
            card = await self._prompts.complete(
                "hermes.pm.validate.card",
                {
                    "initiative": initiative,
                    "prd_path": prd_path(initiative),
                    "findings": _format_findings_for_judge(wave),
                },
                model=self._settings.model_for_lane("pm"),
            )
            return apply_validate_briefs(wave, dict(card.parsed))
        except Exception:
            self.logger.exception("validate card failed; using frozen fallback")
            return apply_validate_briefs(wave, {"briefs": []})

    async def _apply_vf_token(
        self, tenant: TenantContext, room: str, session: HermesSession, token: str
    ) -> None:
        findings = json.loads(session.slots.get(_SLOT_FINDINGS) or "[]")
        decisions = json.loads(session.slots.get(_SLOT_DECISIONS) or "{}")
        wave = json.loads(session.slots.get(_SLOT_WAVE) or "[]")
        if token == "accept-recs":
            for item in wave:
                fid = str(item.get("id") or "")
                if fid:
                    decisions[fid] = str(item.get("recommend") or "fix")
        elif ": explain" in token.lower() or token.lower().endswith(" explain"):
            fid = token.split(":", 1)[0].strip().upper()
            brief_row = next((item for item in wave if str(item.get("id")) == fid), None)
            if brief_row:
                deep = self._briefs.brief_from_validate_finding(
                    brief_row,
                    node_id="requirements-human-decision",
                    purpose="requirements-clarification",
                )
                await self._poster.post_status(
                    room,
                    self._briefs.format_brief_markdown(deep),
                    EventType.PROGRESS,
                )
            session.awaiting = AWAITING_JUDGMENT
            await self._store.save(session)
            return
        else:
            parts = token.split(":", 1)
            if len(parts) == 2:
                decisions[parts[0].strip().upper()] = parts[1].strip().lower()
        session.slots[_SLOT_DECISIONS] = json.dumps(decisions)
        unanswered = [row for row in findings if str(row.get("id") or "") not in decisions]
        if unanswered:
            pass_raw = session.slots.get(_SLOT_VALIDATE_PASS) or "2"
            try:
                pass_number = int(pass_raw)
            except ValueError:
                pass_number = 2
            await self._open_vf_wave(
                tenant,
                room,
                session,
                findings,
                pass_number=pass_number,
                prior=decisions,
            )
            return
        await self._finish_findings(tenant, room, session, findings, decisions)

    async def _finish_findings(
        self,
        tenant: TenantContext,
        room: str,
        session: HermesSession,
        findings: list[dict[str, Any]],
        decisions: dict[str, str],
    ) -> None:
        initiative = session.initiative or ""
        body = format_resolution_markdown(initiative, decisions, findings)
        self._workspace.write_local(tenant, resolution_path(initiative), body)
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        await self._store.save(session)
        decided = ", ".join(f"`{fid}`→`{choice}`" for fid, choice in sorted(decisions.items()))
        await self._poster.post_status(
            room,
            f"Wrote `{resolution_path(initiative)}` ({decided}).",
            EventType.PROGRESS,
        )
        await self._update_pass(tenant, room, session)

    def _auto_owns_pass(self, pass_number: int) -> bool:
        """Think-lane parity: Hermes owns decide+apply inside the auto budget."""
        return pass_number <= int(self._settings.pm_auto_decide_validate_passes)

    async def _update_pass(self, tenant: TenantContext, room: str, session: HermesSession) -> None:
        initiative = session.initiative or ""
        try:
            pass_number = int(session.slots.get(_SLOT_VALIDATE_PASS) or "1")
        except ValueError:
            pass_number = 1
        session.stage = "update-documents"
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        await self._store.save(session)
        interval = int(self._settings.progress_seconds)
        await self._poster.post_status(
            room,
            (
                f"Running `/update-documents` for {initiative} "
                f"(pass {pass_number}; progress every {interval}s)…"
            ),
            EventType.PROGRESS,
            {
                "status": "in_progress",
                "hop": "update-documents",
                "initiative": initiative,
                "pass": pass_number,
            },
        )
        try:
            await self._dispatch.run_skill_node(
                tenant,
                "update-documents",
                initiative,
                on_progress=self._poster.still_working_callback(
                    room,
                    hop="update-documents",
                    initiative=initiative,
                    label="update-documents",
                ),
            )
        except Exception as exc:
            self.logger.exception("update skill failed")
            await self._poster.post_status(
                room,
                f"Update failed for {initiative}: {str(exc)[:200]}",
                EventType.STALL,
            )
            return
        if self._auto_owns_pass(pass_number):
            await self._poster.post_status(
                room,
                (
                    f"**Hermes applied** update-documents for {initiative} "
                    f"(auto pass {pass_number}). Continuing validate…"
                ),
                EventType.PROGRESS,
                {
                    "status": "hermes_update_applied",
                    "initiative": initiative,
                    "pass": pass_number,
                },
            )
            await self._run_validate_cycle(tenant, room, session, pass_number=pass_number + 1)
            return
        session.open_brief = self._briefs.build_brief(
            purpose="update-manifest",
            node_id="update-documents",
            question=f"Apply document updates for {initiative} from your VF decisions?",
            example="Applying updates the promoted PRD from Resolution.",
            options=["apply — update the PRD now", "hold — pause updates"],
            recommend="apply",
            recommend_why="Keep the PRD aligned with what you just decided.",
            reply_tokens=["apply", "hold", "CHG-01: apply", "CHG-01: hold"],
        )
        session.awaiting = AWAITING_JUDGMENT
        await self._store.save(session)
        await self._poster.post_status(
            room,
            self._briefs.format_brief_markdown(session.open_brief),
            EventType.PROGRESS,
            {"status": "need_manifest", "initiative": initiative},
        )

    async def _after_manifest(
        self, tenant: TenantContext, room: str, session: HermesSession, token: str
    ) -> None:
        lowered = token.lower()
        if "hold" in lowered:
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._poster.post_status(
                room,
                f"Held document updates for {session.initiative}.",
                EventType.STALL,
            )
            return
        try:
            pass_number = int(session.slots.get(_SLOT_VALIDATE_PASS) or "1")
        except ValueError:
            pass_number = 1
        await self._run_validate_cycle(tenant, room, session, pass_number=pass_number + 1)

    async def _impact_pass(self, tenant: TenantContext, room: str, session: HermesSession) -> None:
        """Lead-triggered: Impact-Map means the PRD is ready for draft PR auth."""
        initiative = session.initiative or ""
        session.stage = "prd-impact-map"
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        await self._store.save(session)
        interval = int(self._settings.progress_seconds)
        await self._poster.post_status(
            room,
            (f"Running `/prd-impact-map` for {initiative} " f"(progress every {interval}s)…"),
            EventType.PROGRESS,
            {"status": "in_progress", "hop": "prd-impact-map", "initiative": initiative},
        )
        try:
            await self._dispatch.run_skill_node(
                tenant,
                "prd-impact-map",
                initiative,
                on_progress=self._poster.still_working_callback(
                    room,
                    hop="prd-impact-map",
                    initiative=initiative,
                    label="impact-map",
                ),
            )
        except Exception:
            self.logger.exception("impact skill failed")
            await self._poster.post_status(
                room,
                f"Impact map skill failed for {initiative}.",
                EventType.STALL,
            )
            return
        await self._open_forge_auth(tenant, room, session)

    async def _write_post_pm_brief(
        self, tenant: TenantContext, room: str, session: HermesSession
    ) -> None:
        """After validate→review→update budget: decision card before impact-map."""
        initiative = session.initiative or ""
        brief_path = hermes_post_pm_brief_path(initiative)
        interval = int(self._settings.progress_seconds)
        await self._poster.post_status(
            room,
            (
                f"Hermes PM evaluating post-PM artefacts for {initiative} "
                f"(decision card after validate passes; progress every {interval}s)…"
            ),
            EventType.PROGRESS,
            {"status": "in_progress", "hop": "postpm-judge", "initiative": initiative},
        )
        try:
            await self._dispatch.run_hermes_copy(
                tenant,
                "hermes.pm.postpm.judge",
                {
                    "initiative": initiative,
                    "prd_path": prd_path(initiative),
                    "validation_path": validation_report_path(initiative),
                    "resolution_path": resolution_path(initiative),
                    "brief_path": brief_path,
                    "extra": "(none)",
                },
                on_progress=self._poster.still_working_callback(
                    room,
                    hop="postpm-judge",
                    initiative=initiative,
                    label="postpm-judge",
                ),
                label="postpm-judge",
            )
        except Exception as exc:
            self.logger.exception("Hermes post-PM judge failed", initiative=initiative)
            await self._poster.post_status(
                room,
                f"Hermes post-PM judgment failed: {str(exc)[:200]}",
                EventType.STALL,
            )
            return
        await self._reopen_post_pm_brief(tenant, room, session)

    async def _reopen_post_pm_brief(
        self, tenant: TenantContext, room: str, session: HermesSession
    ) -> None:
        """Open/re-open the post-PM confirm gate from the on-disk Hermes brief."""
        initiative = session.initiative or ""
        brief_path = hermes_post_pm_brief_path(initiative)
        judgment = post_pm_brief_from_hermes(self._workspace.read_local(tenant, brief_path))
        if judgment is None:
            judgment = decision_card(
                recommend="confirm",
                bluf=(
                    "Proceed with caution — Hermes delta card missing; "
                    "re-read Validation + Resolution before impact-map."
                ),
                example=(
                    "If you proceed, impact-map runs next, then draft PR auth "
                    "when the ownership map looks right."
                ),
                locking=("Validate→review→update budget finished",),
                not_locking=("Draft PR still needs explicit authorize after impact-map",),
                revise_if=("PRD still wrong after validate — hold and edit before impact-map",),
                card_kind=CARD_POSTPM,
            )
        session.programme = _PROGRAMME
        session.room = room
        session.stage = "prd-impact-acceptance"
        session.open_brief = self._briefs.build_brief(
            purpose="prd-impact-acceptance",
            node_id="prd-impact-acceptance",
            question=(
                f"After validate for {initiative}: proceed (runs impact-map), or hold and revise?"
            ),
            example=judgment.example,
            options=[
                "confirm — proceed; Hermes runs impact-map now",
                "revise — hold; edit PRD / re-run validate first",
            ],
            recommend=judgment.recommend,
            bluf=judgment.bluf,
            card_kind=CARD_POSTPM,
            locking=list(judgment.locking),
            not_locking=list(judgment.not_locking),
            revise_if=list(judgment.revise_if),
            reply_tokens=["confirm", "revise"],
            artefact_path=brief_path,
        )
        session.awaiting = AWAITING_JUDGMENT
        await self._store.save(session)
        await self._poster.post_status(
            room,
            self._briefs.format_brief_markdown(session.open_brief),
            EventType.PROGRESS,
            {
                "status": "need_post_pm_confirm",
                "initiative": initiative,
                "artefact": brief_path,
            },
        )

    async def _after_post_pm_brief(
        self, tenant: TenantContext, room: str, session: HermesSession, token: str
    ) -> None:
        """confirm = post-PM accepted → auto impact-map; revise = stop for offline PRD fix."""
        lowered = token.lower()
        if "revise" in lowered:
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._poster.post_status(
                room,
                (
                    f"Revise requested for {session.initiative} — update the PRD "
                    "offline, then re-run meta-pm (`post-pm` with the initiative bound)."
                ),
                EventType.STALL,
            )
            return
        # confirm → continue the pin: impact-map now, then draft-PR auth.
        await self._poster.post_status(
            room,
            (f"Post-PM brief accepted for {session.initiative} — " "running impact-map next."),
            EventType.PROGRESS,
            {"status": "post_pm_confirmed", "initiative": session.initiative},
        )
        await self._impact_pass(tenant, room, session)

    async def _open_forge_auth(
        self, tenant: TenantContext, room: str, session: HermesSession
    ) -> None:
        """After Impact-Map: PRD is ready — ask Lead to authorize draft PR.

        Slots for forge ``open_draft_pr`` are seeded here; dispatch also fills
        defaults and pushes the draft head via GitHub Contents API (not ``gh``).
        """
        del tenant  # forge uses tenant at authorize time
        session.stage = "prd-pr-action"
        node = self._navigator.current(session)
        # Navigator may still be on impact-map; force forge node if needed.
        if node.node_id != "prd-pr-action":
            session.stage = "prd-pr-action"
            node = self._navigator.current(session)
        init = (session.initiative or "").strip()
        if init:
            session.slots.setdefault("prd_path", prd_path(init))
            session.slots.setdefault("body_path", impact_map_path(init))
            session.slots.setdefault("resolution_path", resolution_path(init))
            session.slots.setdefault("validation_path", validation_report_path(init))
            session.slots.setdefault("head_branch", f"chore/{init}-prd")
            session.slots.setdefault("title", f"[{init}] PRD draft")
        session.open_brief = self._briefs.brief_authorization(node, session.initiative)
        session.awaiting = AWAITING_AUTHORIZATION
        await self._store.save(session)
        impact = impact_map_path(init)
        await self._poster.post_status(
            room,
            (
                f"Impact-Map ready (`{impact}`). "
                "PRD is ready for draft PR — authorize when you want.\n\n"
                + self._briefs.format_brief_markdown(session.open_brief)
            ),
            EventType.PROGRESS,
            {
                "status": "need_pr_authorize",
                "initiative": session.initiative,
                "artefact": impact,
                "head_branch": session.slots.get("head_branch"),
            },
        )


# Back-compat name used by tests / callers.
PostPmBriefJudgment = DecisionCard


def post_pm_brief_from_hermes(body: str) -> Optional[DecisionCard]:
    """Parse Hermes-owned post-PM decision card. None if malformed / empty."""
    return parse_postpm_decision_card(body)
