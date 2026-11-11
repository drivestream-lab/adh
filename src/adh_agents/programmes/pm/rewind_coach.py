"""Human rewind coach — Can / Cannot / Outside ADH → confirm → execute."""

from __future__ import annotations

import json
import re
from typing import Optional

from injector import inject

from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.collaboration.gate_coach import TokenAction
from src.adh_agents.collaboration.human_replies import (
    CANCEL_REWIND,
    CONFIRM_REWIND,
    REWIND,
    normalize_reply,
)
from src.adh_agents.programmes.pm.rewind_execute import RewindExecuteService
from src.adh_agents.runtime.autonomy import AutonomyPolicy
from src.adh_agents.runtime.gate_opener import CoachSpec, GateOpener
from src.adh_agents.runtime.rewind import (
    RewindLadder,
    RewindTarget,
    RewindTargetId,
    RewindTipFacts,
    build_ladder,
    format_ladder_body,
)
from src.adh_agents.runtime.work_models import AWAITING_JUDGMENT, AgentWorkSession
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.buzz_service import BuzzService
from src.logging import get_logger
from src.models.buzz_models import EventType, TaskEventCreate, TaskEventKind
from src.models.tenant_models import TenantContext

logger = get_logger()

_PROGRAMME = "task-rewind"
_PURPOSE_MENU = "task-rewind-menu"
_PURPOSE_CONFIRM = "task-rewind-confirm"
_SLOT_LADDER = "rewind_ladder_json"
_SLOT_PICK = "rewind_pick_id"
_SLOT_REASON = "rewind_reason"
_SLOT_TIP = "rewind_tip"
_SLOT_INIT = "rewind_initiative"
_SLOT_PRIOR = "rewind_prior_json"

_PICK_RE = re.compile(
    r"^\s*rewind\s+(\d+)\s*(?:\n+|;\s*|\s+)?(?:reason\s*:\s*)?(.*)$",
    re.I | re.S,
)
_REASON_LINE = re.compile(r"^\s*reason\s*:\s*(.+)\s*$", re.I | re.M)


class RewindCoachProgramme:
    """Lead ``rewind`` / ``confirm rewind`` / ``cancel`` — human-only."""

    role_id = "adh.pm"

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        poster: HermesBuzzPoster,
        gates: GateOpener,
        briefs: HermesBriefService,
        store: AgentWorkStore,
        autonomy: AutonomyPolicy,
        execute: RewindExecuteService,
    ) -> None:
        self._buzz = buzz
        self._poster = poster
        self._gates = gates
        self._briefs = briefs
        self._store = store
        self._autonomy = autonomy
        self._execute = execute

    async def handle_lead(
        self,
        tenant: TenantContext,
        room: str,
        *,
        body: str,
        lead_handle: str,
        task_id: str | None = None,
    ) -> bool:
        """True when this message was a rewind token / open rewind gate reply."""
        text = (body or "").strip()
        if not text:
            return False

        init = await self._resolve_init(tenant, room, task_id=task_id, body=text)
        session = await self._load_rewind_session(tenant, room, init) if init else None

        # Confirm / cancel against open rewind gate.
        if session is not None and session.open_brief is not None:
            purpose = (session.open_brief.purpose or session.stage or "").strip()
            if purpose == _PURPOSE_CONFIRM:
                token = normalize_reply(text, [CONFIRM_REWIND, CANCEL_REWIND])
                if (
                    token == CANCEL_REWIND
                    or normalize_reply(text, [CANCEL_REWIND]) == CANCEL_REWIND
                ):
                    await self._cancel(tenant, room, session)
                    return True
                if token == CONFIRM_REWIND:
                    await self._confirm(tenant, room, session, lead_handle=lead_handle)
                    return True
                # Still waiting — nudge
                if text.lower() in {REWIND, "rewind"}:
                    await self._poster.post_status(
                        room,
                        f"Confirm pending rewind with `{CONFIRM_REWIND}` or `{CANCEL_REWIND}`.",
                        EventType.STALL,
                    )
                    return True
                return False
            if purpose == _PURPOSE_MENU:
                if normalize_reply(text, [CANCEL_REWIND]) == CANCEL_REWIND or text.lower() in {
                    "cancel",
                    CANCEL_REWIND,
                }:
                    await self._cancel(tenant, room, session)
                    return True
                pick = self._parse_pick(text)
                if pick is not None:
                    await self._on_menu_pick(
                        tenant,
                        room,
                        session,
                        index=pick[0],
                        reason=pick[1],
                        lead_handle=lead_handle,
                    )
                    return True
                if text.lower() == REWIND or text.lower().startswith("rewind"):
                    # Re-show menu
                    await self.open_menu(
                        tenant, room, initiative=init or "", lead_handle=lead_handle
                    )
                    return True
                return False

        # Fresh rewind request (no open rewind gate).
        if text.lower() == REWIND or text.lower().startswith("rewind "):
            # `rewind N` without an open menu — open menu first unless denied.
            await self.open_menu(tenant, room, initiative=init or "", lead_handle=lead_handle)
            # If body was `rewind N` + reason, try to consume immediately after menu.
            pick = self._parse_pick(text)
            if pick is not None and init:
                session = await self._load_rewind_session(tenant, room, init)
                if session is not None and not session.slots.get("rewind_denied"):
                    await self._on_menu_pick(
                        tenant,
                        room,
                        session,
                        index=pick[0],
                        reason=pick[1],
                        lead_handle=lead_handle,
                    )
            return True

        # Bare confirm without gate — ignore
        if normalize_reply(text, [CONFIRM_REWIND]) == CONFIRM_REWIND:
            return False
        return False

    async def open_menu(
        self,
        tenant: TenantContext,
        room: str,
        *,
        initiative: str,
        lead_handle: str = "",
    ) -> None:
        init = (initiative or "").strip().upper()
        if not init:
            await self._poster.post_status(
                room,
                "Say `rewind` from the task room (or include the INIT id) so I know which lane.",
                EventType.STALL,
            )
            return

        await self._poster.ack_received(
            room,
            lead_body=REWIND,
            identity_handle=self.role_id,
        )

        pm = await self._store.load(tenant.slug, self.role_id, init)
        facts = await self._tip_facts(tenant, init, pm)
        ladder = build_ladder(facts)

        if ladder.denied or not ladder.can:
            await self._buzz.append_task_event(
                TaskEventCreate(
                    tenant_slug=tenant.slug,
                    task_id=init,
                    kind=TaskEventKind.REWIND_DENIED,
                    role_id=lead_handle or self.role_id,
                    purpose=ladder.tip_purpose or "rewind",
                    token=REWIND,
                    payload={
                        "reason": ladder.deny_reason,
                        "cannot": list(ladder.cannot),
                        "can": [],
                    },
                )
            )
            body = format_ladder_body(ladder)
            await self._poster.post_status(
                room,
                f"**Rewind denied** for `{init}`.\n\n{body}",
                EventType.STALL,
                {
                    "status": "rewind_denied",
                    "initiative": init,
                    "reason": ladder.deny_reason,
                },
            )
            return

        session = AgentWorkSession(
            tenant_slug=tenant.slug,
            role_id=self.role_id,
            room=room,
            programme=_PROGRAMME,
            stage=_PURPOSE_MENU,
            awaiting=AWAITING_JUDGMENT,
        )
        session.bind_initiative(init)
        session.slots[_SLOT_LADDER] = self._serialize_ladder(ladder)
        session.slots[_SLOT_TIP] = ladder.tip_purpose
        session.slots[_SLOT_INIT] = init
        if pm is not None and pm.programme != _PROGRAMME:
            session.slots[_SLOT_PRIOR] = pm.model_dump_json()
        elif pm is not None and (pm.slots.get(_SLOT_PRIOR) or "").strip():
            # Re-open menu while a rewind gate is already up — keep stashed PM session.
            session.slots[_SLOT_PRIOR] = pm.slots[_SLOT_PRIOR]

        tokens = [TokenAction(f"rewind {i}", t.impact) for i, t in enumerate(ladder.can, start=1)]
        tokens.append(TokenAction(CANCEL_REWIND, "dismiss rewind — keep current tip"))
        recommend = "rewind 1"
        brief = self._briefs.build_brief(
            purpose=_PURPOSE_MENU,
            node_id=_PURPOSE_MENU,
            question=f"How far should we rewind `{init}`?",
            example="Reply `rewind 1` plus `reason: …` (required before confirm).",
            options=[f"rewind {i} — {t.id.value}" for i, t in enumerate(ladder.can, start=1)]
            + [f"{CANCEL_REWIND} — dismiss"],
            recommend=recommend,
            recommend_why="Smallest blast radius first.",
            reply_tokens=[f"rewind {i}" for i in range(1, len(ladder.can) + 1)] + [CANCEL_REWIND],
        )
        # Human-only: never god-take rewind gates.
        if self._autonomy.is_god:
            # Should already be denied via facts.is_god — belt and braces.
            return
        await self._gates.open(
            session,
            brief=brief,
            coach=CoachSpec(
                i_did=f"Mapped rewind options from tip `{ladder.tip_purpose}` for **{init}**.",
                recommend=recommend,
                recommend_why="Smallest blast radius first.",
                evidence=format_ladder_body(ladder),
                outside_adh=(
                    "Anything not listed under Can rewind must be done manually "
                    "(git revert, foreign PRs, CI)."
                ),
                tokens=tokens,
                hop=_PURPOSE_MENU,
                example="`rewind 1` then on the next line `reason: wrong C-pick`",
                payload={
                    "status": "need_rewind_pick",
                    "initiative": init,
                    "purpose": _PURPOSE_MENU,
                    "can": [t.id.value for t in ladder.can],
                },
            ),
        )

    async def _on_menu_pick(
        self,
        tenant: TenantContext,
        room: str,
        session: AgentWorkSession,
        *,
        index: int,
        reason: str,
        lead_handle: str,
    ) -> None:
        ladder = self._deserialize_ladder(session.slots.get(_SLOT_LADDER) or "")
        target = ladder.target_by_index(index) if ladder else None
        if target is None:
            await self._poster.post_status(
                room,
                f"Unknown rewind pick `{index}`. Reply `rewind N` from the Can list, or `{CANCEL_REWIND}`.",
                EventType.STALL,
            )
            return
        reason_clean = (reason or "").strip()
        if not reason_clean:
            await self._poster.post_status(
                room,
                (
                    f"Include a reason with your pick, e.g.\n"
                    f"`rewind {index}`\n`reason: wrong product bet`"
                ),
                EventType.STALL,
                {"status": "rewind_need_reason", "index": index},
            )
            return
        session.slots[_SLOT_PICK] = target.id.value
        session.slots[_SLOT_REASON] = reason_clean
        session.stage = _PURPOSE_CONFIRM
        tokens = [
            TokenAction(CONFIRM_REWIND, f"execute rewind to `{target.id.value}`"),
            TokenAction(CANCEL_REWIND, "abort — keep current tip"),
        ]
        brief = self._briefs.build_brief(
            purpose=_PURPOSE_CONFIRM,
            node_id=_PURPOSE_CONFIRM,
            question=f"Confirm rewind to `{target.id.value}`?",
            example=f"Impact: {target.impact}",
            options=[
                f"{CONFIRM_REWIND} — {target.impact}",
                f"{CANCEL_REWIND} — abort",
            ],
            recommend=CONFIRM_REWIND,
            recommend_why=reason_clean,
            reply_tokens=[CONFIRM_REWIND, CANCEL_REWIND],
        )
        await self._gates.open(
            session,
            brief=brief,
            coach=CoachSpec(
                i_did=(
                    f"Queued rewind to **`{target.id.value}`** for " f"**{session.initiative}**."
                ),
                recommend=CONFIRM_REWIND,
                recommend_why=reason_clean,
                evidence=(
                    f"Tip `{session.slots.get(_SLOT_TIP) or '—'}` → `{target.id.value}`.\n"
                    f"Impact: {target.impact}"
                    + ("; will close open draft PRs we raised" if target.close_prs else "")
                ),
                outside_adh="If this is wrong, cancel — post-merge undo stays outside ADH.",
                tokens=tokens,
                hop=_PURPOSE_CONFIRM,
                payload={
                    "status": "need_rewind_confirm",
                    "initiative": session.initiative,
                    "to_purpose": target.id.value,
                    "reason": reason_clean,
                },
            ),
        )
        del lead_handle

    async def _confirm(
        self,
        tenant: TenantContext,
        room: str,
        session: AgentWorkSession,
        *,
        lead_handle: str,
    ) -> None:
        init = (session.initiative or session.slots.get(_SLOT_INIT) or "").strip().upper()
        pick_id = (session.slots.get(_SLOT_PICK) or "").strip()
        reason = (session.slots.get(_SLOT_REASON) or "").strip()
        tip = (session.slots.get(_SLOT_TIP) or "").strip()
        ladder = self._deserialize_ladder(session.slots.get(_SLOT_LADDER) or "")
        target: Optional[RewindTarget] = None
        if ladder is not None:
            for item in ladder.can:
                if item.id.value == pick_id:
                    target = item
                    break
        if target is None or not init:
            await self._poster.post_status(
                room,
                "Rewind confirm missing pick — say `rewind` again.",
                EventType.STALL,
            )
            await self._store.clear(tenant.slug, self.role_id, init or session.work_id)
            return
        await self._poster.ack_received(
            room, lead_body=CONFIRM_REWIND, identity_handle=self.role_id
        )
        prior = self._prior_session(session)
        # Drop rewind gate session before execute rebuilds PM session.
        await self._store.clear(tenant.slug, self.role_id, init)
        await self._execute.execute(
            tenant,
            room,
            initiative=init,
            target=target,
            reason=reason,
            tip_purpose=tip,
            session=prior,
            lead_handle=lead_handle,
        )

    async def _cancel(self, tenant: TenantContext, room: str, session: AgentWorkSession) -> None:
        init = (session.initiative or "").strip().upper()
        await self._poster.ack_received(room, lead_body=CANCEL_REWIND, identity_handle=self.role_id)
        prior = self._prior_session(session)
        await self._store.clear(tenant.slug, self.role_id, init or session.work_id)
        if prior is not None:
            await self._store.save(prior)
        await self._poster.post_status(
            room,
            f"Rewind cancelled for `{init or '—'}`. Tip unchanged.",
            EventType.PROGRESS,
            {"status": "rewind_cancelled", "initiative": init},
        )

    async def _tip_facts(
        self,
        tenant: TenantContext,
        init: str,
        pm: Optional[AgentWorkSession],
    ) -> RewindTipFacts:
        events = []
        try:
            events = await self._buzz.list_task_events(tenant.slug, init)
        except Exception:
            logger.exception("list_task_events failed for rewind", initiative=init)
        purposes = [str(e.purpose or "") for e in events]
        landed = any(
            (e.kind == TaskEventKind.LAND and "prd" in (e.purpose or "").lower())
            or (e.kind == TaskEventKind.LAND and (e.purpose or "") in {"prd-merge", "merge"})
            for e in events
        )
        merge_sha = ""
        stage = ""
        brief_purpose = ""
        has_gate = False
        has_draft = False
        if pm is not None:
            merge_sha = (pm.slots.get("merge_sha") or "").strip()
            stage = pm.stage or ""
            if pm.open_brief is not None:
                brief_purpose = pm.open_brief.purpose or pm.open_brief.node_id or ""
                has_gate = True
            has_draft = (
                bool(
                    (pm.slots.get("pr_url") or "").strip()
                    or (pm.slots.get("pr_number") or "").strip()
                    or (pm.slots.get("enrich_pr") or "").strip()
                )
                and not merge_sha
            )
        if merge_sha:
            landed = True
        if stage in {"prd-merge", "prd-merged", "prd_merged"}:
            landed = True
        return RewindTipFacts(
            stage=stage,
            brief_purpose=brief_purpose,
            has_open_gate=has_gate,
            merge_sha=merge_sha,
            has_open_draft_pr=has_draft,
            product_landed=landed,
            is_god=self._autonomy.is_god,
            event_purposes=purposes,
        )

    async def _resolve_init(
        self,
        tenant: TenantContext,
        room: str,
        *,
        task_id: str | None,
        body: str,
    ) -> str:
        if task_id:
            return task_id.strip().upper()
        if room.startswith("task-"):
            return room[len("task-") :].upper()
        # Try INIT token in body
        match = re.search(r"\b(INIT-[A-Z0-9-]+)\b", body or "", re.I)
        if match:
            return match.group(1).upper()
        try:
            active = await self._buzz.list_tasks(tenant.slug, include_archived=False)
        except Exception:
            return ""
        if len(active) == 1:
            return active[0].task_id
        return ""

    async def _load_rewind_session(
        self, tenant: TenantContext, room: str, init: str
    ) -> Optional[AgentWorkSession]:
        session = await self._store.load(tenant.slug, self.role_id, init)
        if session is None:
            return None
        if session.programme == _PROGRAMME:
            return session
        # Open brief on PM session may be a rewind purpose if we reused the slot.
        purpose = ""
        if session.open_brief is not None:
            purpose = (session.open_brief.purpose or "").strip()
        if purpose in {_PURPOSE_MENU, _PURPOSE_CONFIRM}:
            return session
        return None

    @staticmethod
    def _prior_session(session: AgentWorkSession) -> Optional[AgentWorkSession]:
        raw = (session.slots.get(_SLOT_PRIOR) or "").strip()
        if not raw:
            return None
        try:
            return AgentWorkSession.model_validate_json(raw)
        except Exception:
            return None

    @staticmethod
    def _parse_pick(body: str) -> Optional[tuple[int, str]]:
        text = (body or "").strip()
        match = _PICK_RE.match(text)
        if not match:
            return None
        index = int(match.group(1))
        rest = (match.group(2) or "").strip()
        reason_match = _REASON_LINE.search(text)
        if reason_match:
            reason = reason_match.group(1).strip()
        else:
            reason = rest
            if reason.lower().startswith("reason:"):
                reason = reason.split(":", 1)[-1].strip()
        return index, reason

    @staticmethod
    def _serialize_ladder(ladder: RewindLadder) -> str:
        rows = []
        for t in ladder.can:
            rows.append(
                {
                    "id": t.id.value,
                    "impact": t.impact,
                    "purge_event": t.purge_event.value,
                    "close_prs": t.close_prs,
                    "resume_purpose": t.resume_purpose,
                }
            )
        return json.dumps(
            {
                "tip": ladder.tip_purpose,
                "denied": ladder.denied,
                "deny_reason": ladder.deny_reason,
                "can": rows,
                "cannot": list(ladder.cannot),
                "outside": list(ladder.outside),
            }
        )

    @staticmethod
    def _deserialize_ladder(raw: str) -> Optional[RewindLadder]:
        if not (raw or "").strip():
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        from src.adh_agents.collaboration.temp_papers import PurgeEvent

        can: list[RewindTarget] = []
        for row in data.get("can") or []:
            try:
                tid = RewindTargetId(str(row["id"]))
                can.append(
                    RewindTarget(
                        id=tid,
                        impact=str(row.get("impact") or ""),
                        purge_event=PurgeEvent(str(row["purge_event"])),
                        close_prs=bool(row.get("close_prs")),
                        resume_purpose=str(row.get("resume_purpose") or ""),
                    )
                )
            except (KeyError, ValueError):
                continue
        return RewindLadder(
            tip_purpose=str(data.get("tip") or ""),
            can=tuple(can),
            cannot=tuple(data.get("cannot") or ()),
            outside=tuple(data.get("outside") or ()),
            denied=bool(data.get("denied")),
            deny_reason=str(data.get("deny_reason") or ""),
        )
