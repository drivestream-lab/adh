"""PE settle after PM answers."""

from __future__ import annotations

from src.adh_agents.programmes.pe.settle import decide_settle


def test_settle_when_answers_ok() -> None:
    d = decide_settle(
        round_number=1,
        max_rounds=2,
        answers_body="## Answers\nBuying the mapped scope.\n",
    )
    assert d.action == "settle"


def test_follow_up_when_unresolved_and_rounds_remain() -> None:
    d = decide_settle(
        round_number=1,
        max_rounds=2,
        answers_body="Open blocker remains — cannot attest yet.",
    )
    assert d.action == "follow_up"


def test_cap_forces_settle() -> None:
    d = decide_settle(
        round_number=2,
        max_rounds=2,
        answers_body="Open blocker remains — cannot attest yet.",
    )
    assert d.action == "settle"
    assert "cap" in d.reason.lower() or "2/2" in d.reason


def test_empty_answers_settle() -> None:
    d = decide_settle(round_number=1, max_rounds=2, answers_body="")
    assert d.action == "settle"
