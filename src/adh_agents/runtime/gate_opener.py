"""Single path to open a Lead gate — human waits; god plays recommend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from injector import inject

from src.adh_agents.collaboration.gate_coach import TokenAction
from src.adh_agents.runtime.autonomy import AutonomyPolicy
from src.adh_agents.runtime.work_models import (
    AWAITING_JUDGMENT,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.buzz_service import BuzzService
from src.logging import get_logger
from src.models.buzz_models import (
    EventType,
    MessageCreate,
    MessageKind,
    TaskEventCreate,
    TaskEventKind,
    TaskState,
)
from src.models.hermes.intent_models import JudgmentRequest

logger = get_logger()


@dataclass(frozen=True)
class CoachSpec:
    """Buzz coach body for one open gate."""

    i_did: str
    recommend: str
    outside_adh: str
    tokens: Sequence[TokenAction]
    recommend_why: str = ""
    evidence: str = ""
    hop: str = ""
    example: str = ""
    payload: Optional[dict] = None
    identity_handle: Optional[str] = None
    event_type: EventType = EventType.PROGRESS


class GateOpener:
    """Save brief + coach; optionally auto-take in god mode."""

    @inject
    def __init__(
        self,
        store: AgentWorkStore,
        poster: HermesBuzzPoster,
        buzz: BuzzService,
        autonomy: AutonomyPolicy,
    ) -> None:
        self._store = store
        self._poster = poster
        self._buzz = buzz
        self._autonomy = autonomy

    async def open(
        self,
        session: AgentWorkSession,
        *,
        brief: JudgmentRequest,
        coach: CoachSpec,
        awaiting: str = AWAITING_JUDGMENT,
    ) -> Optional[str]:
        """Open a gate. Returns god-played token, or None when waiting for Lead."""
        session.open_brief = brief
        session.awaiting = awaiting
        await self._store.save(session)

        purpose = (brief.purpose or brief.node_id or "").strip()
        initiative = (session.initiative or session.work_id or "").strip()
        await self._set_task_state(session, TaskState.GATED)
        await self._emit_event(
            session,
            kind=TaskEventKind.GATE_OPEN,
            purpose=purpose,
            token="",
            payload={"awaiting": awaiting, "recommend": brief.recommend},
        )

        await self._poster.post_human_next(
            session.room,
            i_did=coach.i_did,
            recommend=coach.recommend,
            outside_adh=coach.outside_adh,
            tokens=list(coach.tokens),
            recommend_why=coach.recommend_why,
            evidence=coach.evidence,
            hop=coach.hop,
            example=coach.example,
            event_type=coach.event_type,
            payload=coach.payload,
            identity_handle=coach.identity_handle or session.role_id,
        )

        if not self._autonomy.is_god:
            return None

        # Hermes judgment SSOT for god: brief.recommend, else coach.recommend
        # (forge coaches often say `go ahead` while a stale brief said `authorize`).
        token = self._autonomy.resolve_token(brief)
        if token is None and (coach.recommend or "").strip():
            token = self._autonomy.resolve_token(
                brief.model_copy(update={"recommend": coach.recommend.strip()})
            )
        if token is None:
            shown = (brief.recommend or coach.recommend or "").strip()
            await self._set_task_state(session, TaskState.HALTED)
            await self._emit_event(
                session,
                kind=TaskEventKind.GOD_HALT,
                purpose=purpose,
                token=shown,
                payload={"reason": "recommend not auto-playable"},
            )
            await self._poster.post_status(
                session.room,
                (
                    f"**God mode halt** on `{purpose}` for `{initiative or '—'}` — "
                    f"recommend `{shown or '—'}` is not auto-playable. "
                    "Lead may still reply."
                ),
                EventType.STALL,
                {"status": "god_mode_halt", "purpose": purpose, "initiative": initiative},
                identity_handle="adh.system",
            )
            return None

        ok, reason = await self._autonomy.record_take(
            tenant=session.tenant_slug,
            initiative=initiative or purpose,
            purpose=purpose or token,
        )
        if not ok:
            await self._set_task_state(session, TaskState.HALTED)
            await self._emit_event(
                session,
                kind=TaskEventKind.GOD_HALT,
                purpose=purpose,
                token=token,
                payload={"reason": reason},
            )
            await self._poster.post_status(
                session.room,
                f"**God mode halt** — {reason}.",
                EventType.STALL,
                {"status": "god_mode_halt", "purpose": purpose, "reason": reason},
                identity_handle="adh.system",
            )
            return None

        await self._buzz.post_message(
            session.room,
            MessageCreate(
                identity_handle="adh.system",
                body=f"**God took** `{token}` on `{purpose}` (recommend).",
                kind=MessageKind.EVENT,
                event_type=EventType.PROGRESS,
                payload={
                    "status": "god_taken",
                    "token": token,
                    "purpose": purpose,
                    "initiative": initiative,
                },
            ),
        )
        await self._emit_event(
            session,
            kind=TaskEventKind.GOD_TAKEN,
            purpose=purpose,
            token=token,
            payload={"mode": "god"},
        )
        logger.info(
            "GateOpener god took",
            tenant=session.tenant_slug,
            initiative=initiative,
            purpose=purpose,
            token=token,
        )
        return token

    async def _set_task_state(self, session: AgentWorkSession, state: TaskState) -> None:
        """Durable harness state on ``buzz_tasks`` (kind=init|bug|enhancement stays)."""
        task_id = (session.initiative or session.work_id or "").strip().upper()
        if not task_id or task_id.startswith("__"):
            return
        try:
            await self._buzz.set_task_state(
                session.tenant_slug,
                task_id,
                state,
                role_id=session.role_id,
            )
        except Exception:
            logger.exception(
                "GateOpener task state update failed",
                tenant=session.tenant_slug,
                task_id=task_id,
                state=state.value,
            )

    async def _emit_event(
        self,
        session: AgentWorkSession,
        *,
        kind: TaskEventKind,
        purpose: str,
        token: str,
        payload: Optional[dict] = None,
    ) -> None:
        task_id = (session.initiative or "").strip().upper()
        if not task_id or task_id.startswith("__"):
            return
        try:
            await self._buzz.append_task_event(
                TaskEventCreate(
                    tenant_slug=session.tenant_slug,
                    task_id=task_id,
                    kind=kind,
                    role_id=session.role_id,
                    purpose=purpose,
                    token=token,
                    payload=payload,
                )
            )
        except Exception:
            logger.exception(
                "GateOpener trajectory write failed",
                tenant=session.tenant_slug,
                task_id=task_id,
                kind=kind.value,
            )
