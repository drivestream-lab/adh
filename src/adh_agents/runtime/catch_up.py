"""Catch-up policy — delivery harness resumes from task/gates, not chat history.

ADH orchestrates ``buzz_tasks`` (kind + state) + open Redis gates. Boot catch-up
must never re-run historical Lead lines (C2 / post-pm / …) when the task has
already moved on.
"""

from __future__ import annotations

from collections.abc import Callable

from src.adh_agents.runtime.work_models import (
    AWAITING_AUTHORIZATION,
    AWAITING_JUDGMENT,
    AgentWorkSession,
)
from src.adh_agents.runtime.work_store import AgentWorkStore
from src.logging import get_logger
from src.models.buzz_models import MessageRead

logger = get_logger()


async def should_skip_catch_up(store: AgentWorkStore, tenant: str, role_id: str) -> bool:
    """True when active work sessions exist for this role — avoid duplicate starts."""
    if await store.has_active(tenant, role_id):
        logger.info(
            "catch_up skipped — active agent work sessions present",
            tenant=tenant,
            role=role_id,
        )
        return True
    return False


def open_gate_sessions(sessions: list[AgentWorkSession]) -> list[AgentWorkSession]:
    """Sessions waiting on a Lead reply token (human/god gate)."""
    return [
        s
        for s in sessions
        if s.awaiting in (AWAITING_JUDGMENT, AWAITING_AUTHORIZATION) and s.open_brief is not None
    ]


def latest_unacked_lead(
    rows: list[MessageRead],
    *,
    is_lead: Callable[[MessageRead], bool],
) -> MessageRead | None:
    """Newest Lead line that is not already followed by an ingest ack.

    ``rows`` must be newest-first (Buzz ``list_messages`` default).
    Historical tokens (C2 / post-pm / …) must not replay on every worker boot —
    only the tip Lead line, and only when still unacked.
    """
    newest_idx: int | None = None
    for idx, message in enumerate(rows):
        if is_lead(message):
            newest_idx = idx
            break
    if newest_idx is None:
        return None
    newest = rows[newest_idx]
    for newer in rows[:newest_idx]:
        payload = newer.payload or {}
        if payload.get("status") == "received" and payload.get("ack"):
            return None
        if payload.get("status") in {"recorded", "duplicate"}:
            return None
    return newest
