"""Stall-keep helpers — preserve work sessions across transient failures."""

from __future__ import annotations

from src.adh_agents.runtime.work_models import AgentWorkSession
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.models.buzz_models import EventType

_SLOT_STALLED_HOP = "stalled_hop"
_SLOT_STALLED_REASON = "stalled_reason"


async def mark_stalled(
    store: AgentWorkStore,
    session: AgentWorkSession,
    *,
    hop: str,
    reason: str,
) -> AgentWorkSession:
    """Keep the work unit so Lead / agent can `resume` after a blip."""
    session.slots[_SLOT_STALLED_HOP] = hop or session.stage or ""
    session.slots[_SLOT_STALLED_REASON] = (reason or "")[:500]
    await store.save(session)
    return session


def stalled_notice(*, work_id: str, reason: str) -> tuple[str, EventType]:
    body = f"Stalled `{work_id}`: {reason}. " "Session kept — say `resume` when ready."
    return body, EventType.STALL


def clear_stall_slots(session: AgentWorkSession) -> str:
    """Pop stall metadata; return stalled hop (or stage)."""
    hop = (session.slots.pop(_SLOT_STALLED_HOP, None) or session.stage or "").strip()
    session.slots.pop(_SLOT_STALLED_REASON, None)
    return hop
