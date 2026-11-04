"""Hermes collaborator: Lead message -> recommend -> judge -> execute (ADR 0001)."""

from __future__ import annotations

import re
from typing import Optional, Protocol

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.hermes.collaboration.brief_service import HermesBriefService
from src.business_services.hermes.execution.dispatch_service import HermesDispatchService
from src.business_services.hermes.runtime.navigator_service import HermesNavigatorService
from src.business_services.hermes.runtime.session_store import HermesSessionStoreService
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
_STOP = "stop"
_PENDING_NODE = "pending_node"
_PM_ENTRYPOINT = HermesProgrammeType.META_PM


class ProgrammeRunner(Protocol):
    """Hook that walks a programme once the collaborator has bound an entrypoint."""

    async def start_programme(
        self, tenant: TenantContext, room: str, session: HermesSession
    ) -> None: ...

    async def after_judgment(
        self, tenant: TenantContext, room: str, session: HermesSession, token: str
    ) -> None: ...


class HermesCollaboratorService(BaseBusinessService):
    """Stateful Lead conversation over the workflow catalogue."""

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
        session = await self._store.load(tenant.slug)
        if body.lower() == _STOP:
            await self._store.clear(tenant.slug)
            if session is not None:
                await self._say(room, "Stopped. Session cleared.", EventType.DONE)
            return True
        if session is None:
            session = HermesSession(tenant_slug=tenant.slug, room=room)
        # Authoring programme owns its promote/init briefs — do not steal C-label replies.
        if session.programme == HermesProgrammeType.AUTHORING:
            return False
        if session.awaiting == AWAITING_CLARIFY:
            return await self._on_clarify(tenant, room, session, body)
        brief = session.open_brief
        if session.awaiting == AWAITING_JUDGMENT and brief is not None:
            return await self._on_judgment(tenant, room, session, brief, body)
        if session.awaiting == AWAITING_AUTHORIZATION and brief is not None:
            return await self._on_authorization(tenant, room, session, brief, body)
        return await self._on_fresh(tenant, room, session, body)

    async def _on_clarify(
        self, tenant: TenantContext, room: str, session: HermesSession, body: str
    ) -> bool:
        initiative = self._understand.extract_initiative(body)
        if initiative is None:
            await self._say(room, "I still need an INIT-… id (example: INIT-REALWORLD-001).")
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
            await self._say(room, f"Reply with one of: {_fmt(brief.reply_tokens)} (or `stop`).")
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
                room, f"Not authorized yet. Reply {_fmt(brief.reply_tokens)} (or `stop`)."
            )
            return True
        node = self._navigator.current(session)
        result = await self._dispatch.run_external_action(
            tenant,
            node,
            session.initiative or "",
            authorized=True,
            slots=session.slots,
        )
        self._navigator.advance(session, "pass")
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
