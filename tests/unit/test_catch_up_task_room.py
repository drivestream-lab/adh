"""Task-room catch-up must not replay historical C2 / post-pm on boot."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from src.adh_agents.runtime.catch_up import latest_unacked_lead, open_gate_sessions
from src.adh_agents.runtime.work_models import (
    AWAITING_JUDGMENT,
    AWAITING_NONE,
    AgentWorkSession,
)
from src.models.buzz_models import MessageKind, MessageRead
from src.models.hermes.intent_models import JudgmentRequest


def _msg(
    *,
    handle: str,
    body: str,
    kind: MessageKind = MessageKind.MESSAGE,
    payload: dict | None = None,
) -> MessageRead:
    return MessageRead(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        room_id=uuid4(),
        identity_id=uuid4(),
        identity_handle=handle,
        body=body,
        kind=kind,
        payload=payload,
    )


def test_open_gate_sessions_filters() -> None:
    waiting = AgentWorkSession(
        tenant_slug="realworld",
        role_id="adh.pm",
        room="task-x",
        work_id="INIT-1",
        awaiting=AWAITING_JUDGMENT,
        open_brief=JudgmentRequest(
            purpose="x",
            node_id="x",
            question="?",
            options=["go ahead"],
            recommend="go ahead",
            reply_tokens=["go ahead"],
        ),
    )
    busy = AgentWorkSession(
        tenant_slug="realworld",
        role_id="adh.pm",
        room="task-x",
        work_id="INIT-2",
        awaiting=AWAITING_NONE,
        stage="validate-requirements",
    )
    assert open_gate_sessions([waiting, busy]) == [waiting]


def test_latest_unacked_lead_ignores_history_when_acked() -> None:
    # newest-first
    rows = [
        _msg(
            handle="adh.pm",
            body="Got it — working on `go ahead`.",
            kind=MessageKind.EVENT,
            payload={"status": "received", "ack": True},
        ),
        _msg(handle="nikd10x", body="go ahead"),
        _msg(handle="nikd10x", body="C2"),
        _msg(handle="nikd10x", body="post-pm INIT-REALWORLD-003"),
    ]

    def is_lead(m: MessageRead) -> bool:
        return m.kind == MessageKind.MESSAGE and m.identity_handle == "nikd10x"

    assert latest_unacked_lead(rows, is_lead=is_lead) is None


def test_latest_unacked_lead_returns_tip_only() -> None:
    tip = _msg(handle="nikd10x", body="go ahead")
    rows = [
        tip,
        _msg(handle="nikd10x", body="C2"),
        _msg(handle="nikd10x", body="post-pm INIT-REALWORLD-003"),
    ]

    def is_lead(m: MessageRead) -> bool:
        return m.kind == MessageKind.MESSAGE and m.identity_handle == "nikd10x"

    assert latest_unacked_lead(rows, is_lead=is_lead) is tip
