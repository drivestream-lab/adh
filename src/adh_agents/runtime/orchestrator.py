"""ADH Agents Orchestrator — Lead/ops message -> bind -> gate -> programme (control plane)."""

from __future__ import annotations

from typing import Optional

from injector import inject

from src.adh_agents.runtime.programme_runner import ProgrammeRunner, ProgrammeRunnerRegistry
from src.adh_agents.runtime.work_models import (
    AWAITING_AUTHORIZATION,
    AWAITING_CLARIFY,
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    PROGRAMME_AUTHORING,
    PROGRAMME_META_PM,
    UNBOUND_WORK_ID,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.business_services.base_business_service import BaseBusinessService
from src.adh_agents.collaboration.brief_service import HermesBriefService
from src.adh_agents.execution.dispatch_service import HermesDispatchService
from src.adh_agents.programmes.pm.lead_tokens import initiative_example
from src.adh_agents.catalogue.navigator import HermesNavigatorService
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.adh_agents.understanding.understand_service import (
    HermesUnderstandService,
)
from src.models.buzz_models import EventType, MessageRead
from src.models.hermes.intent_models import ClarifyRequest, IntentCandidate, JudgmentRequest
from src.models.tenant_models import TenantContext

# Free-text hints only (substring) — delivery vocabulary SSOT is catalogue / open brief.
_STOP = "stop"
_STOP_ALL = "stop all"
_PENDING_NODE = "pending_node"
_RESUME_CANDIDATES = "resume_candidates"
_RESUME_INTENT = "resume_intent"


def _mentions_resume(text: str) -> bool:
    return "resume" in (text or "").lower()


def _mentions_post_pm(text: str) -> bool:
    lowered = (text or "").lower().replace("_", " ").replace("-", " ")
    compact = "".join(ch for ch in lowered if ch.isalnum() or ch.isspace())
    return "postpm" in compact.replace(" ", "") or "post pm" in compact


def _looks_like_bare_gate(text: str) -> bool:
    """UX helper for orphan resume — not delivery vocabulary SSOT (brief owns tokens)."""
    line = (text or "").strip().lower()
    if line in {"confirm", "revise", "go ahead", "authorize"}:
        return True
    return line.startswith("authorize ")


class Orchestrator(BaseBusinessService):
    """Role-scoped Lead conversation over the workflow catalogue (parallel work-safe)."""

    @inject
    def __init__(
        self,
        store: AgentWorkStore,
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
        self.role_id = "adh.agent"
        self._registry = ProgrammeRunnerRegistry()

    def bind_role(self, role_id: str) -> None:
        """Each agent process scopes the Orchestrator to its Buzz role."""
        self.role_id = (role_id or "").strip() or "adh.agent"

    def register_programme(self, runner: ProgrammeRunner) -> None:
        self._registry.register(runner)

    def set_programme_runner(self, runner: ProgrammeRunner) -> None:
        """Register the (often sole) programme for this agent process."""
        self.register_programme(runner)

    def _runner_for(self, session: AgentWorkSession) -> Optional[ProgrammeRunner]:
        return self._registry.resolve_for_session(session)

    def _any_runner(self) -> Optional[ProgrammeRunner]:
        return self._registry.primary() or (
            self._registry.all()[0] if self._registry.all() else None
        )

    async def handle_lead_message(
        self, tenant: TenantContext, room: str, message: MessageRead
    ) -> bool:
        """True when this service consumed the message."""
        body = (message.body or "").strip()
        active = await self._store.list_active(tenant.slug, self.role_id)
        unbound = await self._store.load_unbound(tenant.slug, self.role_id)

        if body.lower() == _STOP_ALL:
            await self._ack_ingest(room, body, message)
            await self._store.clear(tenant.slug, self.role_id)
            await self._say(room, "Stopped. All sessions cleared.", EventType.DONE)
            return True
        if body.lower() == _STOP:
            await self._ack_ingest(room, body, message)
            return await self._on_stop(tenant, room, active)

        # Resume-pick / post-pm clarify on unbound session.
        if unbound is not None and unbound.awaiting == AWAITING_CLARIFY:
            await self._ack_ingest(room, body, message)
            if unbound.slots.get(_RESUME_CANDIDATES):
                return await self._on_resume_pick(tenant, room, unbound, body)
            return await self._on_clarify(tenant, room, unbound, body)

        meta_sessions = [s for s in active if s.programme != PROGRAMME_AUTHORING]

        # Hot path: reply token matches exactly one open meta-pm gate.
        open_gates = [
            s
            for s in meta_sessions
            if s.awaiting in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION)
            and s.open_brief is not None
        ]
        gate_hits = self._sessions_matching_gate(meta_sessions, body)
        if len(gate_hits) == 1:
            await self._ack_ingest(room, body, message)
            return await self._dispatch_gate(tenant, room, gate_hits[0], body)
        if len(gate_hits) > 1:
            await self._ack_ingest(room, body, message)
            return await self._ask_init_pick(
                tenant,
                room,
                gate_hits,
                intent=body,
                preface="That reply matches more than one open gate.",
            )
        if len(open_gates) == 1 and not gate_hits:
            # Unmatched reply on the only open gate — ask back (do not clear).
            await self._ack_ingest(room, body, message)
            return await self._dispatch_gate(tenant, room, open_gates[0], body)
        if len(open_gates) > 1 and not gate_hits:
            await self._ack_ingest(room, body, message)
            return await self._ask_init_pick(
                tenant,
                room,
                open_gates,
                intent=body,
                preface="Several open gates — which initiative is this reply for?",
            )

        # Recovery / orphan gate / resume — never silent-drop.
        if _mentions_resume(body) or _looks_like_bare_gate(body):
            await self._ack_ingest(room, body, message)
            return await self._recover(tenant, room, body, meta_sessions)

        # Per-session clarify (bound INIT, pending catalogue node).
        clarifying = [s for s in meta_sessions if s.awaiting == AWAITING_CLARIFY]
        if len(clarifying) == 1:
            await self._ack_ingest(room, body, message)
            return await self._on_clarify(tenant, room, clarifying[0], body)
        if len(clarifying) > 1:
            await self._ack_ingest(room, body, message)
            return await self._ask_init_pick(
                tenant,
                room,
                clarifying,
                intent=body,
                preface="Several programmes are waiting for clarification.",
            )

        # Authoring owns promote / init — do not steal C-label replies.
        if any(s.programme == PROGRAMME_AUTHORING for s in active):
            # Only steal if this looks like meta-pm fresh intent.
            if not (
                _mentions_post_pm(body)
                or self._understand.candidates_for_node_mention(
                    body, init_prefix=tenant.init_prefix
                )
            ):
                return False

        # Fresh catalogue / post-pm intent.
        focus = self._focus_session(meta_sessions, room, tenant.slug)
        # Ack only when fresh intent will actually bind (avoid false ack → authoring).
        if await self._fresh_will_consume(tenant, focus, body):
            await self._ack_ingest(room, body, message)
        return await self._on_fresh(tenant, room, focus, body)

    async def _ack_ingest(self, room: str, body: str, message: MessageRead) -> None:
        """Base premise — Lead must see ingest before long hops."""
        await self._poster.ack_received(
            room,
            lead_body=body,
            identity_handle=self.role_id,
            source_message_id=str(message.id) if message.id else None,
        )

    async def _fresh_will_consume(
        self, tenant: TenantContext, session: AgentWorkSession, body: str
    ) -> bool:
        prefix = tenant.init_prefix
        candidates = self._understand.candidates_for_node_mention(body, init_prefix=prefix)
        if candidates:
            return True
        return _mentions_post_pm(body)

    def _focus_session(
        self, meta_sessions: list[AgentWorkSession], room: str, slug: str
    ) -> AgentWorkSession:
        if len(meta_sessions) == 1:
            return meta_sessions[0]
        return AgentWorkSession(tenant_slug=slug, role_id=self.role_id, room=room)

    def _sessions_matching_gate(
        self, sessions: list[AgentWorkSession], body: str
    ) -> list[AgentWorkSession]:
        hits: list[AgentWorkSession] = []
        for session in sessions:
            brief = session.open_brief
            if brief is None:
                continue
            if session.awaiting == AWAITING_JUDGMENT:
                if match_reply_token(body, brief.reply_tokens) is not None:
                    hits.append(session)
            elif session.awaiting == AWAITING_AUTHORIZATION:
                if match_reply_token(body, brief.reply_tokens) is not None:
                    hits.append(session)
        return hits

    async def _dispatch_gate(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, body: str
    ) -> bool:
        brief = session.open_brief
        if brief is None:
            return False
        if session.awaiting == AWAITING_JUDGMENT:
            return await self._on_judgment(tenant, room, session, brief, body)
        if session.awaiting == AWAITING_AUTHORIZATION:
            return await self._on_authorization(tenant, room, session, brief, body)
        return False

    async def _on_stop(
        self, tenant: TenantContext, room: str, active: list[AgentWorkSession]
    ) -> bool:
        meta = [s for s in active if s.programme != PROGRAMME_AUTHORING]
        if not meta:
            # Let authoring / hermes halt handle empty or authoring-only.
            if not active:
                await self._say(room, "Nothing to stop.", EventType.DONE)
                return True
            return False
        if len(meta) == 1:
            init = meta[0].initiative or UNBOUND_WORK_ID
            await self._store.clear(tenant.slug, self.role_id, init)
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
        meta_sessions: list[AgentWorkSession],
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

        runner = self._any_runner()
        if runner is None:
            await self._say(
                room,
                "Nothing is bound right now, and resume is unavailable (no programme runner).",
                EventType.STALL,
            )
            return True

        # Live Redis sessions (stalled mid-hop or mid-programme) before artefacts.
        # U2/U5: never auto-resume a landed product merge as if it needed another draft PR.
        _MERGED = frozenset({"prd-merged", "prd_merged"})
        live_resume = [
            s
            for s in meta_sessions
            if (s.initiative or "").strip()
            and (s.stage or "").strip() not in _MERGED
            and not (s.slots.get("merge_sha") or "").strip()
            and (
                bool(s.slots.get("stalled_hop"))
                or (
                    bool(s.programme)
                    and s.programme != PROGRAMME_AUTHORING
                    and (s.stage or "").strip()
                    and s.awaiting == AWAITING_NONE
                )
            )
        ]
        if len(live_resume) == 1:
            init = (live_resume[0].initiative or "").strip().upper()
            await runner.resume_programme(tenant, room, init)
            return True
        if len(live_resume) > 1:
            return await self._ask_init_pick(
                tenant,
                room,
                live_resume,
                intent=body,
                preface=(
                    "Several live sessions can be resumed (Redis still holds them). "
                    "Which initiative?"
                ),
            )

        # U5: if every live meta session is already merged, do not fall through to
        # artefact-backed draft-PR authorize (Impact-Map still on disk).
        merged_only = [
            s
            for s in meta_sessions
            if (s.stage or "").strip() in _MERGED or (s.slots.get("merge_sha") or "").strip()
        ]
        if merged_only and not live_resume and not open_gates:
            inits = sorted(
                {(s.initiative or "").strip().upper() for s in merged_only if s.initiative}
            )
            label = ", ".join(f"`{i}`" for i in inits) or "this initiative"
            await self._say(
                room,
                (
                    f"Product PR already merged for {label}. "
                    "No product draft to reopen — waiting on knowledge docs / a new intent."
                ),
                EventType.DONE,
            )
            return True

        merged_inits = {
            (s.initiative or "").strip().upper()
            for s in meta_sessions
            if (s.stage or "").strip() in _MERGED or (s.slots.get("merge_sha") or "").strip()
        }
        resumable = [
            row
            for row in runner.list_resumable(tenant)
            if (row.get("initiative") or "").strip().upper() not in merged_inits
        ]
        if len(resumable) == 1:
            init = resumable[0]["initiative"]
            await self._say(
                room,
                (
                    f"**Session expired or unbound** — resumable from artefacts: "
                    f"`{init}` ({resumable[0].get('hint') or resumable[0].get('gate')}). "
                    "Reopening that gate."
                ),
                EventType.PROGRESS,
            )
            await runner.resume_programme(tenant, room, init)
            # If Lead sent a gate token, try to apply it on the reopened session.
            if _looks_like_bare_gate(body) and not _mentions_resume(body):
                session = await self._store.load(tenant.slug, self.role_id, init)
                if session is not None and session.open_brief is not None:
                    return await self._dispatch_gate(tenant, room, session, body)
            return True
        if len(resumable) > 1:
            await self._say(
                room,
                (
                    "**Session expired or unbound** — highlight which initiative to resume "
                    "(artefact-backed):"
                ),
                EventType.STALL,
            )
            return await self._ask_resumable_pick(tenant, room, resumable, intent=body)

        await self._say(
            room,
            (
                "I can't find an open gate or resumable initiative "
                "(Redis empty and no artefacts). "
                "Paste a new outline, promote a think file, or say `post-pm` once a PRD exists. "
                "If you know the initiative id, reply with it and I will try to bind it "
                f"(example: `{initiative_example(tenant.init_prefix)}`)."
            ),
            EventType.STALL,
        )
        # Keep Lead in a clarify loop so a named initiative can still bind.
        session = AgentWorkSession(
            tenant_slug=tenant.slug,
            role_id=self.role_id,
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
        sessions: list[AgentWorkSession],
        *,
        intent: str,
        preface: str,
    ) -> bool:
        options = sorted({(s.initiative or UNBOUND_WORK_ID) for s in sessions})
        hints = []
        for s in sessions:
            init = s.initiative or UNBOUND_WORK_ID
            gate = s.stage or s.awaiting
            hints.append(f"- `{init}` — {s.programme or 'n/a'} / {gate}")
        await self._say(
            room,
            (f"{preface}\n" + "\n".join(hints) + f"\nReply with one of: {_fmt(options)}."),
            EventType.STALL,
        )
        session = AgentWorkSession(
            tenant_slug=tenant.slug,
            role_id=self.role_id,
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
        session = AgentWorkSession(
            tenant_slug=tenant.slug,
            role_id=self.role_id,
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
        self, tenant: TenantContext, room: str, session: AgentWorkSession, body: str
    ) -> bool:
        raw = session.slots.get(_RESUME_CANDIDATES) or ""
        options = [p.strip() for p in raw.split(",") if p.strip()]
        intent = session.slots.get(_RESUME_INTENT) or "resume"
        initiative = self._understand.extract_initiative(body, tenant.init_prefix)
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
                example = initiative_example(tenant.init_prefix)
                await self._say(
                    room,
                    (
                        f"Still need an initiative id (example: `{example}`), "
                        "or paste an outline / say `post-pm` once a PRD exists."
                    ),
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
        await self._store.clear(tenant.slug, self.role_id, UNBOUND_WORK_ID)
        if intent.lower() == _STOP:
            await self._store.clear(tenant.slug, self.role_id, initiative)
            await self._say(room, f"Stopped. Cleared session for {initiative}.", EventType.DONE)
            return True
        runner = self._any_runner()
        if runner is None:
            await self._say(room, "Resume is unavailable (no programme runner).", EventType.STALL)
            return True
        # Prefer live session if still present; else artefact resume.
        live = await self._store.load(tenant.slug, self.role_id, initiative)
        if live is not None and live.open_brief is not None:
            if _looks_like_bare_gate(intent) or match_reply_token(
                intent, live.open_brief.reply_tokens or []
            ):
                return await self._dispatch_gate(tenant, room, live, intent)
            await self._say(
                room,
                f"Bound `{initiative}`. Reply with: {_fmt(live.open_brief.reply_tokens)}.",
            )
            return True
        await runner.resume_programme(tenant, room, initiative)
        if _looks_like_bare_gate(intent) and not _mentions_resume(intent):
            reopened = await self._store.load(tenant.slug, self.role_id, initiative)
            if reopened is not None and reopened.open_brief is not None:
                return await self._dispatch_gate(tenant, room, reopened, intent)
        return True

    async def _on_clarify(
        self, tenant: TenantContext, room: str, session: AgentWorkSession, body: str
    ) -> bool:
        initiative = self._understand.extract_initiative(body, tenant.init_prefix)
        if initiative is None:
            example = initiative_example(tenant.init_prefix)
            await self._say(
                room,
                f"I still need an initiative id (example: `{example}`).",
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
        session: AgentWorkSession,
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
        runner = self._runner_for(session)
        if runner is not None and session.programme:
            await runner.after_judgment(tenant, room, session, token)
        return True

    async def _on_authorization(
        self,
        tenant: TenantContext,
        room: str,
        session: AgentWorkSession,
        brief: JudgmentRequest,
        body: str,
    ) -> bool:
        token = match_reply_token(body, brief.reply_tokens)
        if token is None:
            await self._say(
                room,
                f"Not authorized yet. Reply {_fmt(brief.reply_tokens)} (or `stop`).",
                EventType.STALL,
            )
            return True
        node = self._navigator.current(session)
        runner = self._runner_for(session)
        # Dev YAML authorize gates (spec-merge, board-tickets-action) are owned by
        # DevEnggProgramme.after_judgment — even when the catalogue node is typed
        # external-action / has forge.action. Catalogue-only roles keep forge dispatch.
        if runner is not None and session.programme and self.role_id == "adh.dev":
            session.handoff_outcome = token
            session.slots[f"reply:{brief.node_id}"] = token
            session.open_brief = None
            session.awaiting = AWAITING_NONE
            await self._store.save(session)
            await self._say(room, f"Recorded `{token}` for {brief.node_id}.")
            await runner.after_judgment(tenant, room, session, token)
            return True
        # Forge only — GitHub App API (Contents + Pulls). Never gh CLI.
        try:
            result = await self._dispatch.run_external_action(
                tenant,
                node,
                session.initiative or "",
                authorized=True,
                slots=session.slots,
            )
        except Exception as exc:
            # Keep the authorize brief open; never let forge failures kill the SSE listener.
            await self._say(
                room,
                (
                    f"Authorize failed for `{brief.node_id}`: {exc}. "
                    f"Reply {_fmt(brief.reply_tokens)} to retry (or `stop`)."
                ),
                EventType.STALL,
            )
            return True
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
        self, tenant: TenantContext, room: str, session: AgentWorkSession, body: str
    ) -> bool:
        prefix = tenant.init_prefix
        candidates = self._understand.candidates_for_node_mention(body, init_prefix=prefix)
        initiative = self._understand.extract_initiative(body, prefix) or session.initiative
        if not candidates and _mentions_post_pm(body):
            entry = self._understand.entrypoint_node(PROGRAMME_META_PM)
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
        clarify = self._understand.clarify_for([top], init_prefix=prefix)
        if clarify is not None:
            return await self._ask_clarify(room, session, top.node_id, clarify)
        return await self._begin(tenant, room, session, top.node_id, initiative or "")

    async def _ask_clarify(
        self, room: str, session: AgentWorkSession, node_id: str, clarify: ClarifyRequest
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
        session: AgentWorkSession,
        node_id: str,
        initiative: str,
    ) -> bool:
        init = (initiative or session.initiative or "").strip()
        if init:
            session.bind_initiative(init)
        session.role_id = self.role_id
        session.stage = node_id
        session.awaiting = AWAITING_NONE
        node = self._navigator.current(session)
        programme = self._navigator.entrypoint_for(node_id)
        if programme is not None:
            session.programme = programme
        elif node.is_external_action() and node.requires_explicit_authorization():
            session.open_brief = self._briefs.brief_authorization(node, session.initiative)
            session.awaiting = AWAITING_AUTHORIZATION
        await self._store.save(session)
        if session.open_brief is not None:
            await self._say(room, self._briefs.format_brief_markdown(session.open_brief))
        else:
            await self._say(room, f"Bound `{node_id}` for {session.initiative or 'n/a'}.")
        runner = self._registry.get(programme) if programme else None
        if programme is not None and runner is not None:
            await runner.start_programme(tenant, room, session)
        return True

    async def _say(self, room: str, body: str, event_type: EventType = EventType.PROGRESS) -> None:
        # Always post as the bound role (PM/PE/KB workers) — never default Hermes handle.
        await self._poster.post_status(room, body, event_type, identity_handle=self.role_id)


def match_reply_token(body: str, tokens: list[str]) -> Optional[str]:
    """Match Lead body to a brief token, including human-reply aliases (U6)."""
    from src.adh_agents.collaboration.human_replies import normalize_reply

    hit = normalize_reply(body, tokens)
    if hit is not None:
        return hit
    # Fallback: exact / prefix without alias table (custom VF tokens etc.).
    lines = [ln.strip().lower() for ln in body.splitlines() if ln.strip()]
    for token in tokens:
        key = token.strip().lower()
        if any(ln == key or ln.startswith(key) for ln in lines):
            return token
    return None


def _fmt(tokens: list[str]) -> str:
    return " / ".join(f"`{t}`" for t in tokens)
