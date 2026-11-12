"""Post-board revise engg — reopen YAML development; never silently rewrite."""

from __future__ import annotations

from dataclasses import dataclass

_ENTRY = "spec-draft"


@dataclass(frozen=True)
class ReviseEnggPolicy:
    """What `revise engg` does after board seed."""

    reopen_stage: str = _ENTRY
    supersede_board: bool = True
    allow_silent_rewrite: bool = False


DEFAULT_REVISE_POLICY = ReviseEnggPolicy()


def apply_revise_engg_slots(
    slots: dict[str, str],
    *,
    policy: ReviseEnggPolicy = DEFAULT_REVISE_POLICY,
) -> dict[str, str]:
    """Mark prior board/plan acceptances superseded; clear accept flags for reopen."""
    out = dict(slots)
    if policy.allow_silent_rewrite:
        raise ValueError("silent rewrite of seeded WorkManifest/tickets is forbidden")
    if policy.supersede_board:
        prior = (out.get("board_seed_marker") or out.get("board_seeded_at") or "").strip()
        if prior:
            out["board_superseded"] = prior
        out["board_seeded"] = "false"
        out.pop("board_seed_marker", None)
        out.pop("board_seeded_at", None)
    for key in (
        "tdd_adr_accepted",
        "coding_ready_accepted",
        "board_authorized",
        "plan_accepted",
        "spec_pr_merged",
        "implementation_plan_current",
        "workmanifest_contract_pass",
    ):
        out.pop(key, None)
    out["revise_engg"] = "1"
    out["reopen_stage"] = policy.reopen_stage
    return out


def is_post_board(slots: dict[str, str]) -> bool:
    return (slots.get("board_seeded") or "").strip().lower() in {"1", "true", "yes"}
