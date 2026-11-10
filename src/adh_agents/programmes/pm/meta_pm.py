"""meta-pm programme: catalogue skills + Lead briefs (replaces post_promote_walk)."""

from __future__ import annotations

import json
from typing import Any, Optional

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.temp_papers import (
    PurgeContext,
    PurgeEvent,
    buzz_purge_notice,
    execute_purge,
)
from src.adh_agents.programmes.pm.decision_card import (
    CARD_POSTPM,
    DecisionCard,
    decision_card,
    parse_postpm_decision_card,
)
from src.adh_agents.programmes.pm.decision_cards import apply_validate_briefs
from src.adh_agents.programmes.pm.pe_glue import PmPeGlueProgramme
from src.adh_agents.execution.dispatch_service import HermesDispatchService
from src.adh_agents.catalogue.navigator import HermesNavigatorService
from src.adh_agents.runtime.autonomy import AutonomyPolicy
from src.adh_agents.runtime.gate_opener import CoachSpec, GateOpener
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.adh_agents.programmes.pm.validation_report import (
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
from src.adh_agents.runtime.work_models import (
    AWAITING_AUTHORIZATION,
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    PROGRAMME_META_PM,
    AgentWorkSession,
)
from src.models.tenant_models import TenantContext

_SLOT_FINDINGS = "meta_pm_findings"
_SLOT_DECISIONS = "meta_pm_decisions"
_SLOT_WAVE = "meta_pm_wave"
_SLOT_VALIDATE_PASS = "meta_pm_validate_pass"
_SLOT_STALLED_HOP = "stalled_hop"
_SLOT_STALLED_REASON = "stalled_reason"
_PROGRAMME = PROGRAMME_META_PM


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
    programme_id = PROGRAMME_META_PM
    role_id = "adh.pm"

    """Walk meta-pm from the catalogue entrypoint with session-backed gates."""

    @inject
    def __init__(
        self,
        store: AgentWorkStore,
        dispatch: HermesDispatchService,
        briefs: HermesBriefService,
        navigator: HermesNavigatorService,
        poster: HermesBuzzPoster,
        workspace: PmWorkspaceService,
        prompts: PromptService,
        pe_glue: PmPeGlueProgramme,
        gates: GateOpener,
        autonomy: AutonomyPolicy,
    ) -> None:
        super().__init__()
        self._store = store
        self._dispatch = dispatch
        self._briefs = briefs
        self._navigator = navigator
        self._poster = poster
        self._workspace = workspace
        self._prompts = prompts
        self._pe_glue = pe_glue
        self._gates = gates
        self._autonomy = autonomy
        self._settings = HermesSettings.get_instance()

    async def start_programme(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
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
        """Artefact-backed recovery candidates: initiative + gate label.

        U5: skip INITs whose product PR already merged (no zombie draft-PR authorize).
        """
        listing = self._workspace.inventory(tenant)
        rows: list[dict[str, str]] = []
        for init in listing.inits:
            # Merged product PRs must not reappear as draft-PR authorize candidates.
            # Live session stage wins when present.
            # (Artefact-only path cannot see Redis; callers with live sessions prefer those.)
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

    async def resume_programme(self, tenant: TenantContext, room: str, work_id: str) -> None:
        """Continue a stalled session, or rebuild the latest gate from artefacts.

        Order: live Redis session for this INIT → continue stage; else artefacts
        (Impact-Map → authorize; post-PM brief → confirm; PRD → validate).
        """
        init = (work_id or "").strip().upper()
        if not init:
            await self._poster.post_status(
                room,
                "Which initiative should I resume? Reply with the programme initiative id.",
                EventType.STALL,
            )
            return
        live = await self._store.load(tenant.slug, self.role_id, init)
        # Live Redis wins even if programme field was omitted by an older stall path.
        if live is not None and (live.programme == _PROGRAMME or bool((live.stage or "").strip())):
            live.programme = _PROGRAMME
            await self._continue_stalled(tenant, room, live)
            return
        session = AgentWorkSession(
            role_id=self.role_id,
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

    async def _continue_stalled(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        """Re-enter the programme from the live session stage after a stall / blip."""
        init = (session.initiative or "").strip().upper()
        hop = (session.slots.get(_SLOT_STALLED_HOP) or session.stage or "").strip()
        session.slots.pop(_SLOT_STALLED_HOP, None)
        session.slots.pop(_SLOT_STALLED_REASON, None)
        session.room = room
        await self._store.save(session)
        await self._poster.post_status(
            room,
            f"Resuming {init} from live session at **{hop or session.stage or 'meta-pm'}**.",
            EventType.PROGRESS,
            {
                "status": "resume_live_session",
                "initiative": init,
                "stage": session.stage,
                "hop": hop,
            },
        )
        if (
            session.awaiting in {AWAITING_JUDGMENT, AWAITING_AUTHORIZATION}
            and session.open_brief is not None
        ):
            if self._autonomy.is_god:
                # Re-enter stage handlers so GateOpener can auto-play Hermes recommend.
                session.awaiting = AWAITING_NONE
                session.open_brief = None
                await self._store.save(session)
            else:
                await self._poster.post_status(
                    room,
                    self._briefs.format_brief_markdown(session.open_brief),
                    EventType.PROGRESS,
                )
                return
        stage = session.stage or hop
        if stage in ("validate-requirements", "requirements-human-decision"):
            pass_number = int(session.slots.get(_SLOT_VALIDATE_PASS) or "1")
            await self._run_validate_cycle(tenant, room, session, pass_number=max(1, pass_number))
            return
        if stage == "update-documents":
            await self._update_pass(tenant, room, session)
            return
        if stage in ("prd-impact-acceptance", "prd-impact-map"):
            if (
                stage == "prd-impact-acceptance"
                and not (
                    self._workspace.read_local(tenant, hermes_post_pm_brief_path(init)) or ""
                ).strip()
            ):
                await self._write_post_pm_brief(tenant, room, session)
                return
            if stage == "prd-impact-acceptance":
                await self._reopen_post_pm_brief(tenant, room, session)
                return
            await self._impact_pass(tenant, room, session)
            return
        if stage in {"prd-merged", "prd_merged"}:
            # U5 — product already landed; never reopen draft-PR authorize.
            await self._poster.post_status(
                room,
                (
                    f"**{init}** product PR already merged. "
                    "No new product draft unless you start an explicit new intent. "
                    "Waiting on KB for knowledge docs."
                ),
                EventType.DONE,
                {"status": "prd_already_merged", "initiative": init},
            )
            return
        if stage == "prd-pr-action":
            await self._open_forge_auth(tenant, room, session)
            return
        if stage == "prd-merge":
            # D2 — reopen merge authorize; never fall back to open_draft_pr.
            await self._pe_glue.reopen_merge_gate(
                tenant,
                room,
                initiative=init,
                pr_url=session.slots.get("pr_url") or "",
                attestation_url=session.slots.get("attestation_url") or "",
            )
            return
        # Unknown stage — fall through to artefact resume without wiping slots.
        # U5: if merge_sha already on session, refuse draft reopen.
        if (session.slots.get("merge_sha") or "").strip():
            await self._poster.post_status(
                room,
                (
                    f"**{init}** already has a landed product merge marker. "
                    "Refusing another product draft PR authorize."
                ),
                EventType.STALL,
                {"status": "refuse_superseding_draft", "initiative": init},
            )
            return
        await self._poster.post_status(
            room,
            (
                f"Live session for {init} is at `{stage or 'unknown'}` — "
                "reopening from artefacts."
            ),
            EventType.PROGRESS,
        )
        # Clear programme briefly so artefact path runs on a fresh shell session.
        shell = AgentWorkSession(
            role_id=self.role_id,
            tenant_slug=tenant.slug,
            room=room,
            initiative=init,
            programme=_PROGRAMME,
            slots=dict(session.slots),
        )
        impact_body = (self._workspace.read_local(tenant, impact_map_path(init)) or "").strip()
        if impact_body:
            await self._open_forge_auth(tenant, room, shell)
            return
        post_pm = (
            self._workspace.read_local(tenant, hermes_post_pm_brief_path(init)) or ""
        ).strip()
        if post_pm:
            await self._reopen_post_pm_brief(tenant, room, shell)
            return
        if (self._workspace.read_local(tenant, prd_path(init)) or "").strip():
            await self.start_programme(tenant, room, shell)
            return
        await self._poster.post_status(
            room,
            f"Cannot continue {init} — no open gate and no resumable artefacts.",
            EventType.STALL,
        )

    async def _mark_stalled(
        self,
        tenant: TenantContext,
        room: str,
        session: AgentWorkSession,
        *,
        hop: str,
        reason: str,
        message: str,
    ) -> None:
        """Keep the INIT session so Lead can `resume` after a transient outage."""
        del tenant  # session already tenant-scoped
        session.slots[_SLOT_STALLED_HOP] = hop
        session.slots[_SLOT_STALLED_REASON] = reason
        session.awaiting = AWAITING_NONE
        await self._store.save(session)
        await self._poster.post_status(
            room,
            message,
            EventType.STALL,
            {
                "status": "stalled",
                "initiative": session.initiative,
                "hop": hop,
                "reason": reason,
            },
        )

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
    ) -> None:
        """Continue after Lead answered an open brief."""
        stage = session.stage
        if stage == "prd-merge":
            await self._pe_glue.after_judgment(tenant, room, session, token)
            return
        if stage in {"pm-pe-answers", "pm-pe-acked"}:
            # U6 dead path — mid-rally human ack removed; ignore stale sessions.
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._poster.post_status(
                room,
                (
                    f"Ignoring obsolete mid-rally ack for {session.initiative} "
                    "(clarifications are agent↔agent now)."
                ),
                EventType.PROGRESS,
            )
            return
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
        session: AgentWorkSession,
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
            await self._mark_stalled(
                tenant,
                room,
                session,
                hop="validate-requirements",
                reason=str(exc)[:200],
                message=(
                    f"Validate failed for {initiative}: {str(exc)[:200]}. "
                    "Session kept — say `resume` when the network is back."
                ),
            )
            return
        if not result.ok:
            await self._mark_stalled(
                tenant,
                room,
                session,
                hop="validate-requirements",
                reason=f"exit {result.exit_code}",
                message=(
                    f"Validate exited {result.exit_code} for {initiative}. "
                    "Session kept — say `resume` to retry."
                ),
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
        session: AgentWorkSession,
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
        from src.adh_agents.collaboration.gate_coach import TokenAction

        brief = self._briefs.build_brief(
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
        body = "\n\n".join(blocks) + "\n\nOr `accept-recs` for this wave only."
        god_token = await self._gates.open(
            session,
            brief=brief,
            coach=CoachSpec(
                i_did=f"Prepared validation findings wave for **{initiative}**.",
                recommend="accept-recs",
                recommend_why=(
                    "Accept Hermes recommendations for this wave when they match your intent."
                ),
                evidence=body[:1500],
                outside_adh="Read the VF cards / validation report in Cursor before deciding.",
                tokens=[
                    TokenAction("accept-recs", "accept Hermes recommendations for this wave"),
                    TokenAction("hold", "park — leave findings open"),
                ],
                hop="requirements-human-decision",
                payload={
                    "status": "need_validate_decisions",
                    "initiative": initiative,
                    "choices": [item.get("id") for item in briefs],
                },
            ),
        )
        if god_token:
            await self._apply_vf_token(tenant, room, session, god_token)

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
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
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
        session: AgentWorkSession,
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

    async def _update_pass(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
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
            await self._mark_stalled(
                tenant,
                room,
                session,
                hop="update-documents",
                reason=str(exc)[:200],
                message=(
                    f"Update failed for {initiative}: {str(exc)[:200]}. "
                    "Session kept — say `resume` when the network is back."
                ),
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
        from src.adh_agents.collaboration.gate_coach import TokenAction

        brief = self._briefs.build_brief(
            purpose="update-manifest",
            node_id="update-documents",
            question=f"Apply document updates for {initiative} from your VF decisions?",
            example="Applying updates the promoted PRD from Resolution.",
            options=["apply — update the PRD now", "hold — pause updates"],
            recommend="apply",
            recommend_why="Keep the PRD aligned with what you just decided.",
            reply_tokens=["apply", "hold", "CHG-01: apply", "CHG-01: hold"],
        )
        god_token = await self._gates.open(
            session,
            brief=brief,
            coach=CoachSpec(
                i_did=f"Prepared document-update options for **{initiative}**.",
                recommend="apply",
                recommend_why="Keep the PRD aligned with what you just decided.",
                outside_adh="Skim Resolution / PRD in Cursor before applying.",
                tokens=[
                    TokenAction("apply", "update the PRD from Resolution now"),
                    TokenAction("hold", "pause updates"),
                ],
                hop="update-documents",
                payload={"status": "need_manifest", "initiative": initiative},
            ),
        )
        if god_token:
            await self._after_manifest(tenant, room, session, god_token)

    async def _after_manifest(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
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

    async def _impact_pass(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
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
        except Exception as exc:
            self.logger.exception("impact skill failed")
            await self._mark_stalled(
                tenant,
                room,
                session,
                hop="prd-impact-map",
                reason=str(exc)[:200],
                message=(
                    f"Impact map skill failed for {initiative}: {str(exc)[:200]}. "
                    "Session kept — say `resume` when the network is back."
                ),
            )
            return
        await self._open_forge_auth(tenant, room, session)

    async def _write_post_pm_brief(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
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
        self, tenant: TenantContext, room: str, session: AgentWorkSession
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
        from src.adh_agents.collaboration.gate_coach import TokenAction

        brief = self._briefs.build_brief(
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
        god_token = await self._gates.open(
            session,
            brief=brief,
            coach=CoachSpec(
                i_did=f"Finished validate for **{initiative}** and wrote the post-PM brief.",
                recommend=judgment.recommend or "confirm",
                recommend_why=judgment.bluf,
                evidence=f"`{brief_path}`",
                outside_adh="Read the post-PM brief / PRD in Cursor before confirming.",
                tokens=[
                    TokenAction("confirm", "proceed — Hermes runs impact-map now"),
                    TokenAction("revise", "hold — edit PRD / re-run validate first"),
                ],
                hop="prd-impact-acceptance",
                example=judgment.example,
                payload={
                    "status": "need_post_pm_confirm",
                    "initiative": initiative,
                    "artefact": brief_path,
                },
            ),
        )
        if god_token:
            await self._after_post_pm_brief(tenant, room, session, god_token)

    async def _after_post_pm_brief(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, token: str
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
        init = (session.initiative or "").strip().upper()
        if init:
            purged = execute_purge(
                self._workspace,
                tenant,
                PurgeEvent.POST_PM_DONE,
                PurgeContext(initiative=init, meta_repo=tenant.meta_repo),
            )
            if purged:
                await self._poster.post_status(
                    room,
                    buzz_purge_notice(PurgeEvent.POST_PM_DONE, init, purged),
                    EventType.PROGRESS,
                    {
                        "status": "temps_purged",
                        "event": PurgeEvent.POST_PM_DONE.value,
                        "initiative": init,
                        "paths": purged,
                    },
                )
        await self._impact_pass(tenant, room, session)

    async def _open_forge_auth(
        self, tenant: TenantContext, room: str, session: AgentWorkSession
    ) -> None:
        """After Impact-Map: PRD is ready — ask Lead to authorize draft PR.

        Slots for forge ``open_draft_pr`` are seeded here; dispatch also fills
        defaults and pushes the draft head via GitHub Contents API (not ``gh``).
        U5: refuse when this INIT already merged a product PR.
        """
        init_check = (session.initiative or "").strip().upper()
        if (session.slots.get("merge_sha") or "").strip() or (session.stage or "").strip() in {
            "prd-merged",
            "prd_merged",
        }:
            await self._poster.post_status(
                room,
                (
                    f"**{init_check}** product PR already merged — "
                    "refusing a superseding product draft authorize."
                ),
                EventType.STALL,
                {"status": "refuse_superseding_draft", "initiative": init_check},
            )
            return
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
        brief = self._briefs.brief_authorization(node, session.initiative)
        impact = impact_map_path(init)
        from src.adh_agents.collaboration.gate_coach import TokenAction

        god_token = await self._gates.open(
            session,
            brief=brief,
            awaiting=AWAITING_AUTHORIZATION,
            coach=CoachSpec(
                i_did=(
                    f"Impact-Map ready for **{init}** (`{impact}`). "
                    "Product write-up is ready for a draft PR."
                ),
                recommend="go ahead",
                recommend_why=(
                    "Open the product draft PR when you are ready — nothing pushes until you authorize."
                ),
                evidence=f"`{impact}`",
                outside_adh=(
                    f"Skim the Impact-Map and PRD in Cursor (`{impact}`, `prd/{init}.md`) "
                    "before authorizing. Do **not** open the PR yourself on GitHub."
                ),
                tokens=[
                    TokenAction("go ahead", "open the product draft PR on meta"),
                    TokenAction("authorize open_draft_pr", "same as go ahead"),
                    TokenAction("hold", "park — no draft PR yet"),
                ],
                hop="prd-pr-action",
                payload={
                    "status": "need_pr_authorize",
                    "initiative": session.initiative,
                    "artefact": impact,
                    "head_branch": session.slots.get("head_branch"),
                    "purpose": "prd-pr-action",
                },
            ),
        )
        if god_token:
            session.handoff_outcome = god_token
            session.slots[f"reply:{brief.node_id}"] = god_token
            try:
                result = await self._dispatch.run_external_action(
                    tenant,
                    node,
                    session.initiative or "",
                    authorized=True,
                    slots=session.slots,
                )
            except Exception as exc:
                await self._poster.post_status(
                    room,
                    f"Authorize failed for `{brief.node_id}`: {exc}. Gate stays open.",
                    EventType.STALL,
                )
                return
            self._navigator.advance(session, "pass")
            session.awaiting = AWAITING_NONE
            session.open_brief = None
            await self._store.save(session)
            await self._poster.post_status(
                room,
                f"Ran `{result.action}` on {result.repo}: {result.url or 'ok'}",
                EventType.DONE,
            )


# Back-compat name used by tests / callers.
PostPmBriefJudgment = DecisionCard


def post_pm_brief_from_hermes(body: str) -> Optional[DecisionCard]:
    """Parse Hermes-owned post-PM decision card. None if malformed / empty."""
    return parse_postpm_decision_card(body)
