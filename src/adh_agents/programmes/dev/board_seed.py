"""Board seed preconditions — YAML predicates + marker after create-board-tickets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional


@dataclass(frozen=True)
class BoardSeedCheck:
    ok: bool
    reason: str = ""


def board_seed_preconditions(slots: dict[str, str]) -> BoardSeedCheck:
    """Fail closed until YAML board-tickets-action requires hold.

    workflow.yaml ``board-tickets-action.requires``:
      - spec-pr-merged
      - implementation-plan-current
      - workmanifest-contract-pass
    Plus coding-readiness / technical-review-approval accepts from the walker.
    """
    needed = (
        ("spec_pr_merged", "spec-pr-merged"),
        ("tdd_adr_accepted", "technical-review-approval (tdd-adr)"),
        ("coding_ready_accepted", "coding-readiness"),
        ("implementation_plan_current", "implementation-plan-current"),
        ("workmanifest_contract_pass", "workmanifest-contract-pass"),
    )
    missing = [label for key, label in needed if not _truthy(slots.get(key))]
    if missing:
        return BoardSeedCheck(
            ok=False,
            reason=f"Board seed blocked — YAML predicates missing: {', '.join(missing)}.",
        )
    if _truthy(slots.get("board_seeded")) and not (
        _truthy(slots.get("revise_engg")) or _truthy(slots.get("reseed_board"))
    ):
        return BoardSeedCheck(
            ok=False,
            reason=(
                "Board already seeded for this INIT — reply `reseed board` to "
                "supersede tickets only, or `revise engg` to reopen from "
                "spec-draft (no silent rewrite)."
            ),
        )
    return BoardSeedCheck(ok=True)


def mark_board_seeded(slots: dict[str, str], *, marker: Optional[str] = None) -> dict[str, str]:
    out = dict(slots)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["board_seeded"] = "true"
    out["board_seeded_at"] = stamp
    out["board_seed_marker"] = (marker or stamp).strip()
    out["board_authorized"] = "true"
    out.pop("revise_engg", None)
    out.pop("reseed_board", None)
    return out


def apply_reseed_board_slots(slots: dict[str, str]) -> dict[str, str]:
    """Supersede prior board seed; keep merge/plan/WM/accept predicates for re-authorize."""
    out = dict(slots)
    prior = (out.get("board_seed_marker") or out.get("board_seeded_at") or "").strip()
    if prior:
        out["board_superseded"] = prior
    out["board_seeded"] = "false"
    out.pop("board_seed_marker", None)
    out.pop("board_seeded_at", None)
    out.pop("board_authorized", None)
    out.pop("board_issue_urls", None)
    out["reseed_board"] = "1"
    return out


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "accepted", "ok"}
