"""PE settle decision after PM answers — follow-up round vs attest (U6)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettleDecision:
    """Whether to run another question round or settle the rally."""

    action: str  # "follow_up" | "settle"
    reason: str


def decide_settle(
    *,
    round_number: int,
    max_rounds: int,
    answers_body: str,
    questions_body: str = "",
) -> SettleDecision:
    """Cap at max_rounds; otherwise settle unless answers clearly demand another pass.

    Greenfield rule (deterministic, no regex SSOT):
    - If round_number >= max_rounds → settle (cap).
    - If answers empty → settle with soft reason (human merge coach will flag).
    - If answers mention explicit follow-up markers → follow_up when rounds remain.
    - Else settle.
    """
    del questions_body  # reserved for richer delta detection
    round_n = max(1, int(round_number or 1))
    cap = max(1, int(max_rounds or 2))
    if round_n >= cap:
        return SettleDecision(
            action="settle",
            reason=f"clarification round cap reached ({round_n}/{cap})",
        )
    text = (answers_body or "").lower()
    if not text.strip():
        return SettleDecision(
            action="settle",
            reason="PM answers missing — settle and let human review before merge",
        )
    follow_markers = (
        "need another round",
        "follow-up required",
        "unresolved",
        "cannot attest",
        "open blocker",
    )
    if any(m in text for m in follow_markers):
        return SettleDecision(
            action="follow_up",
            reason="PM answers flagged unresolved product blockers",
        )
    return SettleDecision(
        action="settle",
        reason="PM answers sufficient for this wave — clarifications settled",
    )
