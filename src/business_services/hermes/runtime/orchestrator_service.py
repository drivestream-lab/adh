"""Hermes collaborator: Lead message -> recommend -> judge -> execute (ADR 0001)."""

from __future__ import annotations

import re
from typing import Optional, Protocol

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.hermes.collaboration.brief_service import HermesBriefService
from src.business_services.hermes.execution.dispatch_service import HermesDispatchService
from src.business_services.hermes.runtime.navigator_service import HermesNavigatorService
from src.business_services.hermes.runtime.session_store import (
    UNBOUND_INITIATIVE,
    HermesSessionStoreService,
)
from src.business_services.hermes.surface.buzz_poster import HermesBuzzPoster
from src.business_services.hermes.understanding.understand_service import (
    HermesUnderstandService,
)
from src.models.buzz_models import EventType, MessageRead
from src.models.hermes.intent_models import ClarifyRequest, IntentCandidate, JudgmentRequest
from src.models.hermes.session_models import (
    AWAITING_AUTHORIZATION,
    AWAITING_CLARIFY,
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    HermesProgrammeType,
    HermesSession,
)
from src.models.tenant_models import TenantContext

# Free-text hint only; routing to the entrypoint still comes from the catalogue.
_POST_PM_HINT = re.compile(r"\bpost[-\s]?pm\b", re.I)
_RESUME_HINT = re.compile(r"\bresume\b", re.I)
_BARE_GATE_TOKEN = re.compile(
    r"^(confirm|revise|go ahead|authorize(?:\s+\S+)?)$",
    re.I,
)
_STOP = "stop"
_STOP_ALL = "stop all"
_PENDING_NODE = "pending_node"
_RESUME_CANDIDATES = "resume_candidates"
_RESUME_INTENT = "resume_intent"
_PM_ENTRYPOINT = HermesProgrammeType.META_PM


class ProgrammeRunner(Protocol):
    """Hook that walks a programme once the collaborator has bound an entrypoint."""

    async def start_programme(
        self, tenant: TenantContext, room: str, session: HermesSession
    ) -> None: ...

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: HermesSession, token: str
    ) -> None: ...

    async def resume_programme(self, tenant: TenantContext, room: str, initiative: str) -> None: ...

    def list_resumable(self, tenant: TenantContext) -> list[dict[str, str]]: ...


class HermesCollaboratorService(BaseBusinessService):
    """Stateful Lead conversation over the workflow catalogue (parallel INIT-safe)."""

    @inject
    def __init__(
        self,
        store: HermesSessionStoreService,
        understand: HermesUnderstandService,
        briefs: HermesBriefService,
        navigator: HermesNavigatorService,
        dispatch: HermesDispatchService,
        poster: HermesBuzzPoster,
    ) -> None:
        super().__init__()
        self._store = store
        self._understand = understand
        self._briefs = briefs
        self._navigator = navigator
        self._dispatch = dispatch
        self._poster = poster
        self._runner: Optional[ProgrammeRunner] = None

    def set_programme_runner(self, runner: ProgrammeRunner) -> None:
        self._runner = runner

    async def handle_lead_message(
        self, tenant: TenantContext, room: str, message: MessageRead
    ) -> bool:
        """True when this service consumed the message."""
        body = (message.body or "").strip()
        active = await self._store.list_active(tenant.slug)
        unbound = await self._store.load_unbound(tenant.slug)

        if body.lower() == _STOP_ALL:
            await self._store.clear(tenant.slug)
            await self._say(room, "Stopped. All sessions cleared.", EventType.DONE)
            return True
        if body.lower() == _STOP:
            return await self._on_stop(tenant, room, active)

        # Resume-pick / post-pm clarify on unbound session.
        if unbound is not None and unbound.awaiting == AWAITING_CLARIFY:
            if unbound.slots.get(_RESUME_CANDIDATES):
                return await self._on_resume_pick(tenant, room, unbound, body)
            return await self._on_clarify(tenant, room, unbound, body)

        meta_sessions = [s for s in active if s.programme != HermesProgrammeType.AUTHORING]

        # Hot path: reply token matches exactly one open meta-pm gate.
        open_gates = [
            s
            for s in meta_sessions
            if s.awaiting in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION)
            and s.open_brief is not None
        ]
        gate_hits = self._sessions_matching_gate(meta_sessions, body)
        if len(gate_hits) == 1:
            return await self._dispatch_gate(tenant, room, gate_hits[0], body)
        if len(gate_hits) > 1:
            return await self._ask_init_pick(
                tenant,
                room,
                gate_hits,
                intent=body,
                preface="That reply matches more than one open gate.",
            )
        if len(open_gates) == 1 and not gate_hits:
            # Unmatched reply on the only open gate — ask back (do not clear).
            return await self._dispatch_gate(tenant, room, open_gates[0], body)
        if len(open_gates) > 1 and not gate_hits:
            return await self._ask_init_pick(
                tenant,
                room,
                open_gates,
                intent=body,
                preface="Several open gates — which initiative is this reply for?",
            )

        # Recovery / orphan gate / resume — never silent-drop.
        if _RESUME_HINT.search(body) or _BARE_GATE_TOKEN.match(body):
            return await self._recover(tenant, room, body, meta_sessions)

        # Per-session clarify (bound INIT, pending catalogue node).
        clarifying = [s for s in meta_sessions if s.awaiting == AWAITING_CLARIFY]
        if len(clarifying) == 1:
            return await self._on_clarify(tenant, room, clarifying[0], body)
        if len(clarifying) > 1:
            return await self._ask_init_pick(
                tenant,
                room,
                clarifying,
                intent=body,
                preface="Several programmes are waiting for clarification.",
            )

        # Authoring owns promote / init — do not steal C-label replies.
        if any(s.programme == HermesProgrammeType.AUTHORING for s in active):
            # Only steal if this looks like meta-pm fresh intent.
            if not (
                _POST_PM_HINT.search(body) or self._understand.candidates_for_node_mention(body)
            ):
                return False

        # Fresh catalogue / post-pm intent.
        focus = self._focus_session(meta_sessions, room, tenant.slug)
        return await self._on_fresh(tenant, room, focus, body)

    def _focus_session(
        self, meta_sessions: list[HermesSession], room: str, slug: str
    ) -> HermesSession:
        if len(meta_sessions) == 1:
            return meta_sessions[0]
        return HermesSession(tenant_slug=slug, room=room)

    def _sessions_matching_gate(
        self, sessions: list[HermesSession], body: str
    ) -> list[HermesSession]:
        hits: list[HermesSession] = []
        for session in sessions:
            brief = session.open_brief
            if brief is None:
                continue
            if session.awaiting == AWAITING_JUDGMENT:
                if match_reply_token(body, brief.reply_tokens) is not None:
                    hits.append(session)
            elif session.awaiting == AWAITING_AUTHORIZATION:
                lowered = body.lower()
                if any(t.lower() in lowered for t in brief.reply_tokens):
                    hits.append(session)
        return hits

    async def _dispatch_gate(
        self, tenant: TenantContext, room: str, session: HermesSession, body: str
    ) -> bool:
        brief = session.open_brief
        if brief is None:
            return False
        if session.awaiting == AWAITING_JUDGMENT:
            return await self._on_judgment(tenant, room, session, brief, body)
        if session.awaiting == AWAITING_AUTHORIZATION:
            return await self._on_authorization(tenant, room, session, brief, body)
        return False

    async def _on_stop(self, tenant: TenantContext, room: str, active: list[HermesSession]) -> bool:
        meta = [s for s in active if s.programme != HermesProgrammeType.AUTHORING]
        if not meta:
            # Let authoring / hermes halt handle empty or authoring-only.
            if not active:
                await self._say(room, "Nothing to stop.", EventType.DONE)
                return True
            return False
        if len(meta) == 1:
            init = meta[0].initiative or UNBOUND_INITIATIVE
            await self._store.clear(tenant.slug, init)
            await self._say(room, f"Stopped. Cleared session for {init}.", EventType.DONE)
            return True
        return await self._ask_init_pick(
            tenant,
            room,
            meta,
            intent=_STOP,
            preface="Several sessions are open. Which should I stop? (or say `stop all`)",
        )

    async def _recover(
        self,
        tenant: TenantContext,
        room: str,
        body: str,
        meta_sessions: list[HermesSession],
    ) -> bool:
        """Ask back / auto-bind when gate or resume cannot resolve a single session."""
        open_gates = [
            s
            for s in meta_sessions
            if s.awaiting in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION)
            and s.open_brief is not None
        ]
        if len(open_gates) == 1:
            return await self._dispatch_gate(tenant, room, open_gates[0], body)
        if len(open_gates) > 1:
            return await self._ask_init_pick(
                tenant,
                room,
                open_gates,
                intent=body,
                preface="Several open gates — which initiative?",
            )

        if self._runner is None:
            await self._say(
                room,
                "Nothing is bound right now, and resume is unavailable (no programme runner).",
                EventType.STALL,
            )
            return True

        resumable = self._runner.list_resumable(tenant)
        if len(resumable) == 1:
            init = resumable[0]["initiative"]
            await self._runner.resume_programme(tenant, room, init)
            # If Lead sent a gate token, try to apply it on the reopened session.
            if _BARE_GATE_TOKEN.match(body) and not _RESUME_HINT.search(body):
                session = await self._store.load(tenant.slug, init)
                if session is not None and session.open_brief is not None:
                    return await self._dispatch_gate(tenant, room, session, body)
            return True
        if len(resumable) > 1:
            return await self._ask_resumable_pick(tenant, room, resumable, intent=body)

        await self._say(
            room,
            (
                "I can't find an open gate or resumable initiative. "
                "Paste a new outline, promote a think file, or say `post-pm` once a PRD exists. "
                "If you know the INIT id, reply with it and I will try to bind it."
            ),
            EventType.STALL,
        )
        # Keep Lead in a clarify loop so a named INIT can still bind.
        session = HermesSession(
            tenant_slug=tenant.slug,
            room=room,
            awaiting=AWAITING_CLARIFY,
            slots={_RESUME_INTENT: body, _RESUME_CANDIDATES: ""},
        )
        await self._store.save(session)
        return True

    async def _ask_init_pick(
        self,
        tenant: TenantContext,
        room: str,
        sessions: list[HermesSession],
        *,
        intent: str,
        preface: str,
    ) -> bool:
        options = sorted({(s.initiative or UNBOUND_INITIATIVE) for s in sessions})
        hints = []
        for s in sessions:
            init = s.initiative or UNBOUND_INITIATIVE
            gate = s.stage or s.awaiting
            hints.append(f"- `{init}` — {s.programme or 'n/a'} / {gate}")
        await self._say(
            room,
            (f"{preface}\n" + "\n".join(hints) + f"\nReply with one of: {_fmt(options)}."),
            EventType.STALL,
        )
        session = HermesSession(
            tenant_slug=tenant.slug,
            room=room,
            awaiting=AWAITING_CLARIFY,
            slots={
                _RESUME_CANDIDATES: ",".join(options),
                _RESUME_INTENT: intent,
            },
        )
        await self._store.save(session)
        return True

    async def _ask_resumable_pick(
        self,
        tenant: TenantContext,
        room: str,
        resumable: list[dict[str, str]],
        *,
        intent: str,
    ) -> bool:
        options = [row["initiative"] for row in resumable]
        hints = [f"- {row['hint']}" for row in resumable]
        await self._say(
            room,
            (
                "Several initiatives look resumable. Which one?\n"
                + "\n".join(hints)
                + f"\nReply with one of: {_fmt(options)}."
            ),
            EventType.STALL,
        )
        session = HermesSession(
            tenant_slug=tenant.slug,
            room=room,
            awaiting=AWAITING_CLARIFY,
            slots={
                _RESUME_CANDIDATES: ",".join(options),
                _RESUME_INTENT: intent,
            },
        )
        await self._store.save(session)
        return True

    async def _on_resume_pick(
        self, tenant: TenantContext, room: str, session: HermesSession, body: str
    ) -> bool:
        raw = session.slots.get(_RESUME_CANDIDATES) or ""
        options = [p.strip() for p in raw.split(",") if p.strip()]
        intent = session.slots.get(_RESUME_INTENT) or "resume"
        initiative = self._understand.extract_initiative(body)
        if initiative is None and options:
            # Exact option match (case-insensitive).
            lowered = body.strip().lower()
            for opt in options:
                if opt.lower() == lowered:
                    initiative = opt
                    break
        if initiative is None:
            if options:
                await self._say(
                    room,
                    f"Still need an initiative. Reply with one of: {_fmt(options)}.",
                    EventType.STALL,
                )
            else:
                await self._say(
                    room,
                    "Still need an INIT-… id, or paste an outline / say `post-pm` once a PRD exists.",
                    EventType.STALL,
                )
            return True
        if (
            options
            and initiative not in options
            and initiative.upper() not in {o.upper() for o in options}
        ):
            await self._say(
                room,
                f"`{initiative}` is not in the list. Reply with one of: {_fmt(options)}.",
                EventType.STALL,
            )
            return True
        await self._store.clear(tenant.slug, UNBOUND_INITIATIVE)
        if intent.lower() == _STOP:
            await self._store.clear(tenant.slug, initiative)
            await self._say(room, f"Stopped. Cleared session for {initiative}.", EventType.DONE)
            return True
        if self._runner is None:
            await self._say(room, "Resume is unavailable (no programme runner).", EventType.STALL)
            return True
        # Prefer live session if still present; else artefact resume.
        live = await self._store.load(tenant.slug, initiative)
        if live is not None and live.open_brief is not None:
            if _BARE_GATE_TOKEN.match(intent) or match_reply_token(
                intent, live.open_brief.reply_tokens or []
            ):
                return await self._dispatch_gate(tenant, room, live, intent)
            await self._say(
                room,
                f"Bound `{initiative}`. Reply with: {_fmt(live.open_brief.reply_tokens)}.",
            )
            return True
        await self._runner.resume_programme(tenant, room, initiative)
        if _BARE_GATE_TOKEN.match(intent) and not _RESUME_HINT.search(intent):
            reopened = await self._store.load(tenant.slug, initiative)
            if reopened is not None and reopened.open_brief is not None:
                return await self._dispatch_gate(tenant, room, reopened, intent)
        return True

    async def _on_clarify(
        self, tenant: TenantContext, room: str, session: HermesSession, body: str
    ) -> bool:
        initiative = self._understand.extract_initiative(body)
        if initiative is None:
            await self._say(
                room,
                "I still need an INIT-… id (example: INIT-REALWORLD-001).",
                EventType.STALL,
            )
            return True
        session.awaiting = AWAITING_NONE
        node_id = session.slots.pop(_PENDING_NODE, "")
        if not node_id:
            session.initiative = initiative
            await self._store.save(session)
            return True
        return await self._begin(tenant, room, session, node_id, initiative)

    async def _on_judgment(
        self,
        tenant: TenantContext,
        room: str,
        session: HermesSession,
        brief: JudgmentRequest,
        body: str,
    ) -> bool:
        token = match_reply_token(body, brief.reply_tokens)
        if token is None:
            await self._say(
                room,
                f"Reply with one of: {_fmt(brief.reply_tokens)} (or `stop`).",
                EventType.STALL,
            )
            return True
        session.handoff_outcome = token
        session.slots[f"reply:{brief.node_id}"] = token
        session.open_brief = None
        session.awaiting = AWAITING_NONE
        await self._store.save(session)
        await self._say(room, f"Recorded `{token}` for {brief.node_id}.")
        if self._runner is not None and session.programme:
            await self._runner.after_judgment(tenant, room, session, token)
        return True

    async def _on_authorization(
        self,
        tenant: TenantContext,
        room: str,
        session: HermesSession,
        brief: JudgmentRequest,
        body: str,
    ) -> bool:
        lowered = body.lower()
        if not any(t.lower() in lowered for t in brief.reply_tokens):
            await self._say(
                room,
                f"Not authorized yet. Reply {_fmt(brief.reply_tokens)} (or `stop`).",
                EventType.STALL,
            )
            return True
        node = self._navigator.current(session)
        # Forge only — GitHub App API (Contents + Pulls). Never gh CLI.
        result = await self._dispatch.run_external_action(
            tenant,
            node,
            session.initiative or "",
            authorized=True,
            slots=session.slots,
        )
        self._navigator.advance(session, "pass")
        session.awaiting = AWAITING_NONE
        session.open_brief = None
        await self._store.save(session)
        await self._say(
            room,
            f"Ran `{result.action}` on {result.repo}: {result.url or 'ok'}",
            EventType.DONE,
        )
        return True

    async def _on_fresh(
        self, tenant: TenantContext, room: str, session: HermesSession, body: str
    ) -> bool:
        candidates = self._understand.candidates_for_node_mention(body)
        initiative = self._understand.extract_initiative(body) or session.initiative
        if not candidates and _POST_PM_HINT.search(body):
            entry = self._understand.entrypoint_node(_PM_ENTRYPOINT)
            candidates = [
                IntentCandidate(
                    node_id=entry.node_id,
                    confidence=0.6,
                    rationale="free-text post-pm routed to catalogue entrypoint",
                    missing_slots=["initiative"],
                )
            ]
        if not candidates:
            return False
        top = candidates[0]
        if initiative:
            top = top.model_copy(
                update={
                    "missing_slots": [s for s in top.missing_slots if s != "initiative"],
                    "slots": {**top.slots, "initiative": initiative},
                }
            )
        clarify = self._understand.clarify_for([top])
        if clarify is not None:
            return await self._ask_clarify(room, session, top.node_id, clarify)
        return await self._begin(tenant, room, session, top.node_id, initiative or "")

    async def _ask_clarify(
        self, room: str, session: HermesSession, node_id: str, clarify: ClarifyRequest
    ) -> bool:
        session.awaiting = AWAITING_CLARIFY
        session.slots[_PENDING_NODE] = node_id
        await self._store.save(session)
        await self._say(room, clarify.question)
        return True

    async def _begin(
        self,
        tenant: TenantContext,
        room: str,
        session: HermesSession,
        node_id: str,
        initiative: str,
    ) -> bool:
        session.initiative = initiative or session.initiative
        session.stage = node_id
        session.awaiting = AWAITING_NONE
        node = self._navigator.current(session)
        programme = self._navigator.entrypoint_for(node_id)
        if programme is not None:
            session.programme = HermesProgrammeType(programme)
        elif node.is_external_action() and node.requires_explicit_authorization():
            session.open_brief = self._briefs.brief_authorization(node, session.initiative)
            session.awaiting = AWAITING_AUTHORIZATION
        await self._store.save(session)
        if session.open_brief is not None:
            await self._say(room, self._briefs.format_brief_markdown(session.open_brief))
        else:
            await self._say(room, f"Bound `{node_id}` for {session.initiative or 'n/a'}.")
        if programme is not None and self._runner is not None:
            await self._runner.start_programme(tenant, room, session)
        return True

    async def _say(self, room: str, body: str, event_type: EventType = EventType.PROGRESS) -> None:
        await self._poster.post_status(room, body, event_type)


def match_reply_token(body: str, tokens: list[str]) -> Optional[str]:
    """Exact (case-insensitive) or line-prefix match against the brief's own tokens."""
    lines = [ln.strip().lower() for ln in body.splitlines() if ln.strip()]
    for token in tokens:
        key = token.strip().lower()
        if any(ln == key or ln.startswith(key) for ln in lines):
            return token
    return None


def _fmt(tokens: list[str]) -> str:
    return " / ".join(f"`{t}`" for t in tokens)
