"""Board seed preconditions + marker after create-board-tickets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional


@dataclass(frozen=True)
class BoardSeedCheck:
    ok: bool
    reason: str = ""


def board_seed_preconditions(slots: dict[str, str]) -> BoardSeedCheck:
    """Fail closed until deps + tdd/adr + coding-ready are accepted."""
    needed = (
        ("deps_accepted", "deps-acceptance"),
        ("tdd_adr_accepted", "tdd-adr-acceptance"),
        ("coding_ready_accepted", "coding-readiness"),
    )
    missing = [label for key, label in needed if not _truthy(slots.get(key))]
    if missing:
        return BoardSeedCheck(
            ok=False,
            reason=f"Board seed blocked — accept first: {', '.join(missing)}.",
        )
    if _truthy(slots.get("board_seeded")) and not _truthy(slots.get("revise_engg")):
        return BoardSeedCheck(
            ok=False,
            reason=(
                "Board already seeded for this INIT — use `revise engg` to supersede "
                "and re-seed (no silent rewrite)."
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
    return out


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "accepted", "ok"}
